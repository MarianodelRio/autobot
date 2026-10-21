"""Smoke tests for the settings and the Django project (T-0.1)."""

import os
import subprocess
import sys
from pathlib import Path

from django.conf import settings

ROOT = Path(__file__).resolve().parent.parent


def run(*args: str, **env: str) -> subprocess.CompletedProcess[str]:
    base = {
        k: v
        for k, v in os.environ.items()
        if k not in ("ENVIRONMENT", "DJANGO_SECRET_KEY", "DB_OWNER_URL")
    }
    return subprocess.run(
        [sys.executable, *args],
        cwd=ROOT,
        env={**base, **env},
        capture_output=True,
        text=True,
        check=False,
    )


def test_local_settings_load() -> None:
    assert settings.ENVIRONMENT == "local"
    assert settings.DATABASES["default"]["ENGINE"] == "django.db.backends.postgresql"
    assert settings.USE_TZ


def test_manage_check_passes_without_database() -> None:
    result = run("manage.py", "check", DB_APP_URL="postgres://u:p@127.0.0.1:1/none")
    assert result.returncode == 0, result.stderr


def test_prod_requires_secret_key() -> None:
    result = run("manage.py", "check", ENVIRONMENT="prod")
    assert result.returncode != 0
    assert "DJANGO_SECRET_KEY" in result.stderr


def test_prod_with_all_variables_passes_check() -> None:
    result = run(
        "-c",
        "import sys; sys.path.insert(0, 'src');"
        "import config.settings as s; assert not s.DEBUG; assert s.ALLOWED_HOSTS == ['api.x']",
        ENVIRONMENT="prod",
        DJANGO_SECRET_KEY="k",
        DJANGO_ALLOWED_HOSTS="api.x,",
        DB_APP_URL="postgres://u:p@127.0.0.1:1/none",
        SECRETS_FILE="/run/secrets/secrets.yaml",
        WHATSAPP_GRAPH_VERSION="v23.0",
    )
    assert result.returncode == 0, result.stderr


def test_unknown_environment_is_rejected() -> None:
    result = run("manage.py", "check", ENVIRONMENT="staging")
    assert result.returncode != 0
    assert "ENVIRONMENT" in result.stderr


def test_owner_alias_only_when_configured() -> None:
    code = (
        "import sys; sys.path.insert(0, 'src'); import config.settings as s;"
        "print(sorted(s.DATABASES))"
    )
    assert run("-c", code).stdout.strip() == "['default', 'owner']"
    assert run("-c", code, DB_OWNER_URL="").stdout.strip() == "['default']"
