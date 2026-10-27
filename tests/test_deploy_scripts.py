"""Backup and rollback scripts, run against stub commands so nothing real is touched."""

import os
import stat
import subprocess

import pytest

from tests.conftest import ROOT


def _stub_bin(tmp_path, log):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name in ("docker", "systemctl", "curl", "pg_dump", "pg_restore"):
        script = bin_dir / name
        extra = ""
        if name == "pg_dump":
            extra = (
                'for a in "$@"; do case "$a" in --file=*) echo dump > "${a#--file=}";; esac; done\n'
            )
        script.write_text(f'#!/usr/bin/env bash\necho "{name} $*" >> "{log}"\n{extra}exit 0\n')
        script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return bin_dir


def _run(script, args, tmp_path, extra_env=None):
    log = tmp_path / "calls.log"
    log.touch()
    env = {**os.environ, "PATH": f"{_stub_bin(tmp_path, log)}:{os.environ['PATH']}"}
    env.update(extra_env or {})
    result = subprocess.run(
        ["bash", str(ROOT / "deploy" / script), *args],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
    )
    return result, log.read_text()


def test_backup_writes_verifies_and_rotates(tmp_path):
    backups = tmp_path / "bk"
    backups.mkdir()
    for i in range(1, 9):
        (backups / f"test-2020010{i}T000000Z.dump").write_text("old")
    env = {
        "DATABASE_URL": "postgresql+psycopg2://u:secretpw@h/db",
        "BACKUP_DIR": str(backups),
        "BACKUP_KEEP": "3",
    }
    result, calls = _run("backup.sh", [], tmp_path, env)
    assert result.returncode == 0, result.stderr
    assert "secretpw" not in result.stdout + result.stderr
    assert "pg_restore --list" in calls  # verification step ran
    assert "postgresql://u:secretpw@h/db" in calls  # driver suffix was dropped for pg_dump
    assert len(list(backups.glob("test-*.dump"))) == 3  # rotation kept the newest 3


def test_backup_requires_database_url(tmp_path):
    result, _ = _run("backup.sh", [], tmp_path, {"DATABASE_URL": ""})
    assert result.returncode != 0


def test_test_rollback_restarts_previous_tag(tmp_path):
    result, calls = _run("rollback.sh", ["test"], tmp_path, {"PREV_TAG": "v41"})
    assert result.returncode == 0, result.stderr
    assert "docker compose" in calls and "up -d --no-build" in calls


def test_test_rollback_needs_previous_tag(tmp_path):
    result, _ = _run("rollback.sh", ["test"], tmp_path, {"PREV_TAG": ""})
    assert result.returncode != 0


def test_prod_rollback_refuses_without_owner_confirmation(tmp_path):
    result, calls = _run("rollback.sh", ["prod"], tmp_path)
    assert result.returncode == 3
    assert calls.strip() == ""


def test_prod_rollback_stops_new_stack_and_starts_v1(tmp_path):
    env = {"TG_BOT_TOKEN": "1234567890:" + "T" * 35}
    result, calls = _run("rollback.sh", ["prod", "--confirm-owner"], tmp_path, env)
    assert result.returncode == 0, result.stderr
    order = [line.split()[0] + " " + line.split()[1] for line in calls.strip().splitlines()]
    assert order[0] == "docker compose"
    assert any(line.startswith("curl") and "deleteWebhook" in line for line in calls.splitlines())
    assert "systemctl start airobotbro-edu" in calls
    assert "systemctl is-active" in calls
    assert "T" * 35 not in result.stdout + result.stderr  # token never printed


@pytest.mark.parametrize("target", ["test", "prod"])
def test_dry_run_changes_nothing(tmp_path, target):
    args = [target, "--dry-run"] + (["--confirm-owner"] if target == "prod" else [])
    result, calls = _run("rollback.sh", args, tmp_path, {"PREV_TAG": "v41"})
    assert result.returncode == 0
    assert calls.strip() == ""
