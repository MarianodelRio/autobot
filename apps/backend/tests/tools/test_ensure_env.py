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
    "AUTOBOT_IMAGE": "ghcr.io/example-owner/autobot",
    "AUTOBOT_PANEL_IMAGE": "ghcr.io/example-owner/autobot-panel",
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
# Generated only once the externals above are present (A5, A6): derived from them,
# or from the host the script runs on, never required to be set by hand.
DERIVED_NAMES = {"DEPLOY_UID", "PUBLIC_URL"}


@pytest.fixture
def script(tmp_path: Path) -> Path:
    scripts = tmp_path / "deploy" / "scripts"
    scripts.mkdir(parents=True)
    path = scripts / "ensure-env.sh"
    shutil.copy(ROOT / "deploy/scripts/ensure-env.sh", path)
    path.chmod(0o755)
    # A4: a regular file is required before the script will proceed; most tests
    # exercise other checks and don't care about its content.
    (tmp_path / "var").mkdir()
    (tmp_path / "var" / "google_sa.json").write_text("{}\n")
    return path


def run(script: Path, *args: str, **environment: str) -> subprocess.CompletedProcess[str]:
    # CI's own job env already sets the DB_*_URL (and FP_*_PASSWORD) that make
    # check needs; strip them so the script sees a clean slate like a real .env.
    base = {
        k: v
        for k, v in os.environ.items()
        if k not in GENERATED_NAMES | DERIVED_NAMES | set(EXTERNALS)
    }
    return subprocess.run(
        ["bash", str(script), *args],
        cwd=script.parents[2],
        env={**base, **environment},
        capture_output=True,
        text=True,
        check=False,
    )


def first(script: Path, **environment: str) -> subprocess.CompletedProcess[str]:
    """A first install: the only case where the encryption key may be generated (ADR-022)."""
    return run(script, "--first-install", **environment)


def env_dict(tmp_path: Path) -> dict[str, str]:
    lines = (tmp_path / ".env").read_text().splitlines()
    return dict(line.split("=", 1) for line in lines if line and not line.startswith("#"))


def test_generates_missing_internals_without_the_externals(script: Path, tmp_path: Path) -> None:
    result = first(script)
    assert result.returncode == 1, result.stderr
    assert "PUBLIC_HOST" in result.stderr
    assert "DJANGO_ALLOWED_HOSTS" in result.stderr
    assert "AUTOBOT_IMAGE" in result.stderr
    assert "AUTOBOT_PANEL_IMAGE" in result.stderr
    env = env_dict(tmp_path)
    assert set(env) == GENERATED_NAMES
    assert env["DB_APP_URL"] == f"postgres://fp_app:{env['FP_APP_PASSWORD']}@db:5432/autobot"
    assert (tmp_path / ".env").stat().st_mode & 0o777 == 0o600


def test_derives_deploy_uid_and_public_url_once_externals_are_set(
    script: Path, tmp_path: Path
) -> None:
    """A5, A6: neither is set by hand; both come from the host and PUBLIC_HOST."""
    result = first(script, **EXTERNALS)
    assert result.returncode == 0, result.stderr
    env = env_dict(tmp_path)
    assert env["DEPLOY_UID"] == str(os.getuid())
    assert env["PUBLIC_URL"] == "https://api.example.com"


def test_deploy_uid_is_rederived_even_if_already_set_to_another_host(
    script: Path, tmp_path: Path
) -> None:
    (tmp_path / ".env").write_text("DEPLOY_UID=999999\n")
    result = first(script, **EXTERNALS)
    assert result.returncode == 0, result.stderr
    assert env_dict(tmp_path)["DEPLOY_UID"] == str(os.getuid())


def test_refuses_to_run_as_root(script: Path, tmp_path: Path) -> None:
    """A6: run as root by mistake, DEPLOY_UID=0 would run every container as root."""
    binaries = tmp_path / "bin"
    binaries.mkdir()
    fake_id = binaries / "id"
    fake_id.write_text("#!/usr/bin/env bash\necho 0\n")
    fake_id.chmod(0o755)
    result = first(script, **EXTERNALS, PATH=f"{binaries}:{os.environ['PATH']}")
    assert result.returncode == 1
    assert "never as root" in result.stderr
    assert "DEPLOY_UID=0" not in (tmp_path / ".env").read_text()


def test_rejects_missing_google_sa_json(script: Path, tmp_path: Path) -> None:
    (tmp_path / "var" / "google_sa.json").unlink()
    result = first(script, **EXTERNALS)
    assert result.returncode == 1
    assert "google_sa.json" in result.stderr


def test_rejects_google_sa_json_as_a_directory(script: Path, tmp_path: Path) -> None:
    """A4: Docker creates a directory in its place when the bind-mount source is
    missing; ensure-env.sh must refuse that just as it refuses a missing file."""
    (tmp_path / "var" / "google_sa.json").unlink()
    (tmp_path / "var" / "google_sa.json").mkdir()
    result = first(script, **EXTERNALS)
    assert result.returncode == 1
    assert "google_sa.json" in result.stderr


def test_never_prints_a_generated_value(script: Path) -> None:
    result = first(script, **EXTERNALS)
    for value in (result.stdout + result.stderr).splitlines():
        assert "postgres://" not in value or "db:5432/autobot" not in value
    assert "Generated:" in result.stdout
    for secret_name in GENERATED_NAMES:
        # Only the bare name is printed, never "NAME=<secret>".
        assert f"{secret_name}=" not in result.stdout


def test_succeeds_and_changes_nothing_once_everything_is_set(script: Path, tmp_path: Path) -> None:
    first(script, **EXTERNALS)
    env_file = script.parents[2] / ".env"
    before = env_file.read_text()

    result = first(script, **EXTERNALS)

    assert result.returncode == 0, result.stderr
    assert env_file.read_text() == before


def test_rejects_allowed_hosts_missing_the_tunnel_hosts(script: Path) -> None:
    result = first(script, **{**EXTERNALS, "DJANGO_ALLOWED_HOSTS": "api.example.com"})
    assert result.returncode == 1
    assert "DJANGO_ALLOWED_HOSTS" in result.stderr


def test_rejects_example_secret_key_already_in_env(script: Path, tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("DJANGO_SECRET_KEY=change-me\n")
    result = first(script, **EXTERNALS)
    assert result.returncode == 1
    assert "DJANGO_SECRET_KEY" in result.stderr


def test_rejects_example_encryption_key_already_in_env(script: Path, tmp_path: Path) -> None:
    (tmp_path / ".env").write_text(
        "SECRETS_ENCRYPTION_KEY=UHx17yr1uv1SdskJ5dGpF1MYUPfD2ierqd5mY_2AQ_w=\n"
    )
    result = first(script, **EXTERNALS)
    assert result.returncode == 1
    assert "SECRETS_ENCRYPTION_KEY" in result.stderr


def test_rejects_db_url_pointing_at_localhost(script: Path, tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("DB_APP_URL=postgres://fp_app:fp_app@localhost:5433/autobot\n")
    result = first(script, **EXTERNALS)
    assert result.returncode == 1
    assert "DB_APP_URL" in result.stderr


def test_never_overwrites_an_existing_external_value(script: Path, tmp_path: Path) -> None:
    (tmp_path / ".env").write_text(
        "PUBLIC_HOST=already.example.com\n"
        "DJANGO_ALLOWED_HOSTS=already.example.com,localhost,127.0.0.1\n"
        "DEPLOY_UID=1234\n"
        "AUTOBOT_IMAGE=ghcr.io/example-owner/autobot\n"
        "AUTOBOT_PANEL_IMAGE=ghcr.io/example-owner/autobot-panel\n"
    )
    result = first(script)
    assert result.returncode == 0, result.stderr
    assert "already.example.com,localhost,127.0.0.1" in (tmp_path / ".env").read_text()


def test_db_urls_follow_a_rotated_password(script: Path, tmp_path: Path) -> None:
    """Rotating FP_APP_PASSWORD in .env must not leave DB_APP_URL with the old one."""
    first(script, **EXTERNALS)
    initial = env_dict(tmp_path)
    (tmp_path / ".env").write_text(
        "\n".join(f"{k}={v}" for k, v in initial.items() if k != "FP_APP_PASSWORD")
        + "\nFP_APP_PASSWORD=rotated-secret\n"
    )
    result = first(script, **EXTERNALS)
    assert result.returncode == 0, result.stderr
    assert "DB_APP_URL did not match FP_APP_PASSWORD" in result.stderr
    assert "rotated-secret" not in result.stdout + result.stderr
    assert env_dict(tmp_path)["DB_APP_URL"] == "postgres://fp_app:rotated-secret@db:5432/autobot"


def test_missing_encryption_key_aborts_without_first_install(script: Path, tmp_path: Path) -> None:
    """ADR-022: no key on an existing install means restore it, never silently replace it."""
    first(script, **EXTERNALS)
    env = env_dict(tmp_path)
    del env["SECRETS_ENCRYPTION_KEY"]
    (tmp_path / ".env").write_text("".join(f"{k}={v}\n" for k, v in env.items()))
    before = (tmp_path / ".env").read_text()

    result = run(script, **EXTERNALS)

    assert result.returncode == 1
    assert "SECRETS_ENCRYPTION_KEY" in result.stderr
    assert "rotar-secretos.md" in result.stderr
    assert (tmp_path / ".env").read_text() == before


def test_missing_encryption_key_on_a_fresh_env_aborts_without_first_install(
    script: Path, tmp_path: Path
) -> None:
    result = run(script, **EXTERNALS)
    assert result.returncode == 1
    assert "SECRETS_ENCRYPTION_KEY" not in env_dict(tmp_path)


def test_first_install_generates_the_encryption_key_once(script: Path, tmp_path: Path) -> None:
    result = first(script, **EXTERNALS)
    assert result.returncode == 0, result.stderr
    key = env_dict(tmp_path)["SECRETS_ENCRYPTION_KEY"]
    assert len(key) == 44
    assert key not in result.stdout + result.stderr
    # Re-running (with or without the flag) keeps the same key.
    assert first(script, **EXTERNALS).returncode == 0
    assert run(script, **EXTERNALS).returncode == 0
    assert env_dict(tmp_path)["SECRETS_ENCRYPTION_KEY"] == key


def test_an_existing_key_needs_no_flag(script: Path, tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("SECRETS_ENCRYPTION_KEY=" + "a" * 43 + "=\n")
    result = run(script, **EXTERNALS)
    assert result.returncode == 0, result.stderr
    assert env_dict(tmp_path)["SECRETS_ENCRYPTION_KEY"] == "a" * 43 + "="


def test_rejects_unknown_arguments(script: Path) -> None:
    assert run(script, "--bogus", **EXTERNALS).returncode == 2
