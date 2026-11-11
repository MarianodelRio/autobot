"""Smoke tests for the settings and the Django project."""

import os
import subprocess
import sys
from pathlib import Path

from django.conf import settings

ROOT = Path(__file__).resolve().parent.parent.parent


def run(*args: str, **env: str) -> subprocess.CompletedProcess[str]:
    base = {
        k: v
        for k, v in os.environ.items()
        if k
        not in (
            "ENVIRONMENT",
            "DJANGO_SECRET_KEY",
            "DB_OWNER_URL",
            "DB_READONLY_URL",
            "SECRETS_ENCRYPTION_KEY",
        )
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


def test_demo_telegram_users_must_be_ids() -> None:
    code = "import sys; sys.path.insert(0, 'src'); import config.settings as s;"
    code += " print(sorted(s.DEMO_TELEGRAM_USERS))"
    ok = run("-c", code, DEMO_TELEGRAM_USERS="12, 34 56")
    assert ok.stdout.strip() == "[12, 34, 56]", ok.stderr
    bad = run("manage.py", "check", DEMO_TELEGRAM_USERS="12,abc")
    assert bad.returncode != 0 and "DEMO_TELEGRAM_USERS" in bad.stderr


def test_demo_telegram_webhook_secret_must_be_long() -> None:
    result = run("manage.py", "check", DEMO_TELEGRAM_WEBHOOK_SECRET="short")
    assert result.returncode != 0 and "DEMO_TELEGRAM_WEBHOOK_SECRET" in result.stderr


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
        SECRETS_ENCRYPTION_KEY="r9QT0J-HCiYMurCE7CqrNd-Cxb8WIxoYsw3XekIvUoU=",
        WHATSAPP_GRAPH_VERSION="v23.0",
    )
    assert result.returncode == 0, result.stderr


def test_prod_rejects_example_secret_key() -> None:
    result = run(
        "manage.py",
        "check",
        ENVIRONMENT="prod",
        DJANGO_SECRET_KEY="change-me",
        SECRETS_ENCRYPTION_KEY="UHx17yr1uv1SdskJ5dGpF1MYUPfD2ierqd5mY_2AQ_w=",
        DB_APP_URL="postgres://u:p@127.0.0.1:1/none",
    )
    assert result.returncode != 0
    assert "DJANGO_SECRET_KEY" in result.stderr


def test_prod_rejects_example_encryption_key() -> None:
    result = run(
        "manage.py",
        "check",
        ENVIRONMENT="prod",
        DJANGO_SECRET_KEY="a-real-key",
        SECRETS_ENCRYPTION_KEY="UHx17yr1uv1SdskJ5dGpF1MYUPfD2ierqd5mY_2AQ_w=",
        DB_APP_URL="postgres://u:p@127.0.0.1:1/none",
    )
    assert result.returncode != 0
    assert "SECRETS_ENCRYPTION_KEY" in result.stderr


def test_prod_rejects_db_urls_pointing_at_localhost() -> None:
    for name in ("DB_APP_URL", "DB_OWNER_URL", "DB_READONLY_URL"):
        env_vars = {
            "ENVIRONMENT": "prod",
            "DJANGO_SECRET_KEY": "a-real-key",
            "DJANGO_ALLOWED_HOSTS": "api.x",
            "SECRETS_ENCRYPTION_KEY": "r9QT0J-HCiYMurCE7CqrNd-Cxb8WIxoYsw3XekIvUoU=",
            "DB_APP_URL": "postgres://u:p@db.internal:5432/none",
            name: "postgres://u:p@localhost:5433/autobot",
        }
        result = run("manage.py", "check", **env_vars)
        assert result.returncode != 0, name
        assert name in result.stderr, name


def test_unknown_environment_is_rejected() -> None:
    result = run("manage.py", "check", ENVIRONMENT="staging")
    assert result.returncode != 0
    assert "ENVIRONMENT" in result.stderr


def test_victorialogs_handler_only_when_configured() -> None:
    code = (
        "import sys; sys.path.insert(0, 'src'); import config.settings as s;"
        "print('victorialogs' in s.LOGGING['root']['handlers'])"
    )
    assert run("-c", code).stdout.strip() == "False"
    assert run("-c", code, VICTORIALOGS_URL="http://victorialogs:9428").stdout.strip() == "True"


def test_owner_and_readonly_alias_only_when_configured() -> None:
    code = (
        "import sys; sys.path.insert(0, 'src'); import config.settings as s;"
        "print(sorted(s.DATABASES))"
    )
    assert run("-c", code).stdout.strip() == "['default', 'owner', 'readonly']"
    assert run("-c", code, DB_OWNER_URL="", DB_READONLY_URL="").stdout.strip() == "['default']"
    assert run("-c", code, DB_READONLY_URL="").stdout.strip() == "['default', 'owner']"


def test_prod_rejects_invalid_encryption_key_without_disclosing_it() -> None:
    for key in ("invalid-private-key", "r9QT0J-HCiYMurCE7CqrNd-Cxb8WIxoYsw3XekIvUoU=,bad-key", ","):
        result = run(
            "-c",
            "import sys; sys.path.insert(0, 'src'); import config.settings",
            ENVIRONMENT="prod",
            DJANGO_SECRET_KEY="k",
            SECRETS_ENCRYPTION_KEY=key,
        )
        assert result.returncode != 0
        assert "ImproperlyConfigured" in result.stderr
        assert "SECRETS_ENCRYPTION_KEY must contain valid Fernet keys" in result.stderr
        for part in filter(None, key.split(",")):
            assert part not in result.stderr
