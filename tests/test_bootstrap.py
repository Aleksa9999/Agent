"""Server bootstrap: the resource check and the .env writer (nothing is installed in tests)."""

import os
import stat
import subprocess

from tests.conftest import ROOT

SCRIPT = str(ROOT / "deploy" / "bootstrap-server.sh")
SECRET_TOKEN = "987654:AAH-secret_token&with/odd|chars"


def _meminfo(tmp_path, kb):
    path = tmp_path / "meminfo"
    path.write_text(f"MemTotal:       {kb} kB\nMemFree:        1 kB\n")
    return str(path)


def _os(tmp_path, ident="ubuntu", version="22.04"):
    path = tmp_path / "os-release"
    path.write_text(f'ID={ident}\nVERSION_ID="{version}"\n')
    return str(path)


def _check(tmp_path, *, kb=8_000_000, ident="ubuntu", version="22.04", disk_kb=60_000_000):
    env = {
        **os.environ,
        "BOOTSTRAP_MEMINFO": _meminfo(tmp_path, kb),
        "BOOTSTRAP_OS_RELEASE": _os(tmp_path, ident, version),
        "BOOTSTRAP_DISK_KB": str(disk_kb),
    }
    return subprocess.run(["bash", SCRIPT, "check"], env=env, capture_output=True, text=True)


def test_a_server_with_enough_memory_and_disk_is_suitable(tmp_path):
    result = _check(tmp_path)
    assert result.returncode == 0 and "RESULT : suitable" in result.stdout
    assert "memory : 7812 MB" in result.stdout


def test_the_current_890_mb_server_is_rejected(tmp_path):
    result = _check(tmp_path, kb=911_360, disk_kb=8_800_000)
    assert result.returncode == 1
    assert "not enough memory" in result.stdout and "not enough free disk" in result.stdout


def test_other_systems_are_rejected(tmp_path):
    result = _check(tmp_path, ident="debian", version="12")
    assert result.returncode == 1 and "Ubuntu 22.04 or 24.04" in result.stdout


def _write_env(tmp_path, answers: str):
    (tmp_path / ".env.example").write_text((ROOT / ".env.example").read_text())
    target = tmp_path / ".env.test"
    env = {**os.environ, "ENV_OUT": str(target)}
    result = subprocess.run(
        ["bash", SCRIPT, "env"],
        cwd=tmp_path,
        env=env,
        input=answers,
        capture_output=True,
        text=True,
    )
    return result, target


def _values(path):
    return dict(line.split("=", 1) for line in path.read_text().splitlines() if "=" in line)


ANSWERS = f"{SECRET_TOKEN}\n42\n-1001234\nhttps://app.example.test\nqwen-key-value\nmodel-big\nmodel-small\n"


def test_env_file_gets_random_passwords_the_answers_and_private_permissions(tmp_path):
    result, target = _write_env(tmp_path, ANSWERS)
    assert result.returncode == 0, result.stderr
    values = _values(target)
    assert values["TG_TEST_BOT_TOKEN"] == SECRET_TOKEN  # odd characters survive
    assert values["OWNER_TG_ID"] == "42" and values["WEBAPP_URL"] == "https://app.example.test"
    assert values["QWEN_MODEL"] == "model-big" and values["APP_ENV"] == "test"
    for name in ("POSTGRES_PASSWORD", "REDIS_PASSWORD", "TG_WEBHOOK_SECRET"):
        assert len(values[name]) == 48 and set(values[name]) <= set("0123456789abcdef")
    assert len({values["POSTGRES_PASSWORD"], values["REDIS_PASSWORD"]}) == 2
    assert stat.S_IMODE(target.stat().st_mode) == 0o600


def test_secrets_are_never_printed(tmp_path):
    result, target = _write_env(tmp_path, ANSWERS)
    output = result.stdout + result.stderr
    values = _values(target)
    for secret in (
        SECRET_TOKEN,
        "qwen-key-value",
        values["POSTGRES_PASSWORD"],
        values["TG_WEBHOOK_SECRET"],
    ):
        assert secret not in output


def test_a_second_run_keeps_existing_values_and_asks_only_for_what_is_missing(tmp_path):
    _, target = _write_env(tmp_path, ANSWERS)
    before = _values(target)
    result, _ = _write_env(tmp_path, "")  # nothing typed: nothing may change
    assert result.returncode == 0
    assert _values(target) == before


def test_a_required_value_cannot_be_left_empty(tmp_path):
    result, target = _write_env(tmp_path, "\n")
    assert result.returncode != 0 and "TG_TEST_BOT_TOKEN is required" in result.stderr
    assert not target.exists()
