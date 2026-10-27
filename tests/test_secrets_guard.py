"""A secret staged in git must be blocked by gitleaks (the same tool as pre-commit and CI)."""

import secrets
import shutil
import string
import subprocess

import pytest

from tests.conftest import ROOT

pytestmark = pytest.mark.skipif(
    shutil.which("gitleaks") is None, reason="gitleaks is not installed"
)


def _git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)


def _fake_github_token() -> str:
    alphabet = string.ascii_letters + string.digits
    return "ghp_" + "".join(secrets.choice(alphabet) for _ in range(36))


def _scan(repo):
    return subprocess.run(
        [
            "gitleaks",
            "git",
            "--staged",
            "--no-banner",
            "--redact",
            "--config",
            str(ROOT / ".gitleaks.toml"),
            str(repo),
        ],
        capture_output=True,
        text=True,
    )


def test_staged_secret_is_blocked(tmp_path):
    _git(tmp_path, "init", "-q")
    (tmp_path / "config.py").write_text(f'TOKEN = "{_fake_github_token()}"\n', encoding="utf-8")
    _git(tmp_path, "add", "config.py")
    result = _scan(tmp_path)
    assert result.returncode != 0
    assert "ghp_" not in result.stdout + result.stderr  # redacted in the report


def test_clean_change_passes(tmp_path):
    _git(tmp_path, "init", "-q")
    (tmp_path / "readme.txt").write_text("nothing secret here\n", encoding="utf-8")
    _git(tmp_path, "add", "readme.txt")
    assert _scan(tmp_path).returncode == 0
