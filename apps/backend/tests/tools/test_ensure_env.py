"""`deploy/scripts/ensure-env.sh`: generates missing internal secrets, leaves existing
ones alone, never prints a value, and aborts listing whatever external one is missing."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
EXTERNALS = {
    "PUBLIC_HOST": "api.example.com",
    "DJANGO_ALLOWED_HOSTS": "api.example.com,localhost,127.0.0.1",
    "DEPLOY_UID": "10001",
}
GENERATED_NAMES = {
    "FP_OWNER_PASSWORD",
    "FP_APP_PASSWORD",
    "FP_READONLY_PASSWORD",
    "POSTGRES_PASSWORD",
    "DJANGO_SECRET_KEY",
    "DEMO_TELEGRAM_WEBHOOK_SECRET",
    "NOTIFY_BOT_WEBHOOK_SECRET",
    "SECRETS_ENCRYPTION_KEY",
    "DB_APP_URL",
    "DB_OWNER_URL",
    "DB_READONLY_URL",
    "COMPOSE_FILE",
    "COMPOSE_PROJECT_NAME",
}


@pytest.fixture
def script(tmp_path: Path) -> Path:
    scripts = tmp_path / "deploy" / "scripts"
    scripts.mkdir(parents=True)
    path = scripts / "ensure-env.sh"
    shutil.copy(ROOT / "deploy/scripts/ensure-env.sh", path)
    path.chmod(0o755)
    return path


def run(script: Path, **environment: str) -> subprocess.CompletedProcess[str]:
    # CI's own job env already sets the DB_*_URL (and FP_*_PASSWORD) that make
    # check needs; strip them so the script sees a clean slate like a real .env.
    base = {k: v for k, v in os.environ.items() if k not in GENERATED_NAMES | set(EXTERNALS)}
    return subprocess.run(
        ["bash", str(script)],
        cwd=script.parents[2],
        env={**base, **environment},
        capture_output=True,
        text=True,
        check=False,
    )


def env_dict(tmp_path: Path) -> dict[str, str]:
    lines = (tmp_path / ".env").read_text().splitlines()
    return dict(line.split("=", 1) for line in lines if line and not line.startswith("#"))


def test_generates_missing_internals_without_the_externals(script: Path, tmp_path: Path) -> None:
    result = run(script)
    assert result.returncode == 1, result.stderr
    assert "PUBLIC_HOST" in result.stderr
    assert "DJANGO_ALLOWED_HOSTS" in result.stderr
    assert "DEPLOY_UID" in result.stderr
    env = env_dict(tmp_path)
    assert set(env) == GENERATED_NAMES
    assert env["DB_APP_URL"] == f"postgres://fp_app:{env['FP_APP_PASSWORD']}@db:5432/autobot"
    assert (tmp_path / ".env").stat().st_mode & 0o777 == 0o600


def test_never_prints_a_generated_value(script: Path) -> None:
    result = run(script, **EXTERNALS)
    for value in (result.stdout + result.stderr).splitlines():
        assert "postgres://" not in value or "db:5432/autobot" not in value
    assert "Generated:" in result.stdout
    for secret_name in GENERATED_NAMES:
        # Only the bare name is printed, never "NAME=<secret>".
        assert f"{secret_name}=" not in result.stdout


def test_succeeds_and_changes_nothing_once_everything_is_set(script: Path, tmp_path: Path) -> None:
    run(script, **EXTERNALS)
    env_file = script.parents[2] / ".env"
    before = env_file.read_text()

    result = run(script, **EXTERNALS)

    assert result.returncode == 0, result.stderr
    assert env_file.read_text() == before


def test_rejects_allowed_hosts_missing_the_tunnel_hosts(script: Path) -> None:
    result = run(script, **{**EXTERNALS, "DJANGO_ALLOWED_HOSTS": "api.example.com"})
    assert result.returncode == 1
    assert "DJANGO_ALLOWED_HOSTS" in result.stderr


def test_never_overwrites_an_existing_external_value(script: Path, tmp_path: Path) -> None:
    (tmp_path / ".env").write_text(
        "PUBLIC_HOST=already.example.com\n"
        "DJANGO_ALLOWED_HOSTS=already.example.com,localhost,127.0.0.1\n"
        "DEPLOY_UID=1234\n"
    )
    result = run(script)
    assert result.returncode == 0, result.stderr
    assert "already.example.com,localhost,127.0.0.1" in (tmp_path / ".env").read_text()
