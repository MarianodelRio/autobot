"""Django settings, read from environment variables (design.md §5.3).

`ENVIRONMENT=local` (the default) provides development defaults; `ENVIRONMENT=prod`
requires every secret to be set explicitly.
"""

import importlib.util
import os
from pathlib import Path
from typing import Any

import dj_database_url
from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent.parent

ENVIRONMENT = os.environ.get("ENVIRONMENT", "local")
if ENVIRONMENT not in ("local", "prod"):
    raise ImproperlyConfigured(f"ENVIRONMENT must be 'local' or 'prod', not {ENVIRONMENT!r}")
IS_LOCAL = ENVIRONMENT == "local"


def env(name: str, local_default: str | None = None) -> str:
    """Return a required variable; in local, fall back to `local_default`."""
    value = os.environ.get(name)
    if value:
        return value
    if IS_LOCAL and local_default is not None:
        return local_default
    raise ImproperlyConfigured(f"Missing environment variable {name}")


SECRET_KEY = env("DJANGO_SECRET_KEY", "local-insecure-secret-key")
DEBUG = IS_LOCAL
_hosts = env("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")
ALLOWED_HOSTS = [h.strip() for h in _hosts.split(",") if h.strip()]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "procrastinate.contrib.django",
    "flowpilot",
]
# Development-only: provides `lintmigrations` for CI (design.md §17.3); absent from the image.
if importlib.util.find_spec("django_migration_linter"):
    INSTALLED_APPS.append("django_migration_linter")
    # Third-party migrations (Procrastinate) are not ours to fix; every app of ours is linted.
    MIGRATION_LINTER_OPTIONS = {"exclude_apps": ["procrastinate"]}

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]


# Two aliases (design.md §12.2): `default` is fp_app (no BYPASSRLS, no DDL), used by web
# and worker; `owner` is fp_owner (owns the tables, BYPASSRLS), used only by migrations,
# the Admin and operation commands. The worker runs without DB_OWNER_URL, so without the
# alias. Local defaults match compose.yaml, whose db is published on port 5433.
def _database(url: str) -> dict[str, Any]:
    return dict(dj_database_url.parse(url, conn_max_age=60, conn_health_checks=True))


DATABASES = {
    "default": _database(env("DB_APP_URL", "postgres://fp_app:fp_app@localhost:5433/flowpilot")),
}
# Unset → local default; set but empty (the worker) → no `owner` alias.
_owner_url = os.environ.get(
    "DB_OWNER_URL", "postgres://fp_owner:fp_owner@localhost:5433/flowpilot" if IS_LOCAL else ""
)
if _owner_url:
    DATABASES["owner"] = _database(_owner_url)

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Job queue (design.md §7.5): Procrastinate on the `default` alias (fp_app); jobs are
# declared in flowpilot/jobs.py.
PROCRASTINATE_AUTODISCOVER_MODULE_NAME = "jobs"

# Tenants (design.md §5): config in git, channel secrets on the server (in local, the
# repository root, ignored by git).
TENANTS_DIR = Path(os.environ.get("TENANTS_DIR", BASE_DIR / "tenants"))
SECRETS_FILE = Path(env("SECRETS_FILE", str(BASE_DIR / "secrets.yaml")))

# Channels (design.md §6). Graph API version of the WhatsApp Cloud API (reviewed every six
# months, §16.4).
WHATSAPP_GRAPH_VERSION = env("WHATSAPP_GRAPH_VERSION", "v23.0")


def _ids(name: str) -> frozenset[int]:
    raw = os.environ.get(name, "")
    try:
        return frozenset(int(part) for part in raw.replace(",", " ").split())
    except ValueError:
        raise ImproperlyConfigured(f"{name} must be Telegram user ids") from None


# The platform's test bot (§6.5). Without a token it is off; without a webhook secret its
# webhook is off (local development uses `telegram_poll`).
TEST_BOT_TOKEN = os.environ.get("TEST_BOT_TOKEN", "")
TEST_BOT_WEBHOOK_SECRET = os.environ.get("TEST_BOT_WEBHOOK_SECRET", "")
if TEST_BOT_WEBHOOK_SECRET and len(TEST_BOT_WEBHOOK_SECRET) < 32:
    raise ImproperlyConfigured("TEST_BOT_WEBHOOK_SECRET must have 32 characters or more")
TEST_BOT_OPERATORS = _ids("TEST_BOT_OPERATORS")  # they see every business

LANGUAGE_CODE = "es-es"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": os.environ.get("LOG_LEVEL", "INFO")},
    # httpx logs every request URL at INFO, and Telegram's carries the bot token (§13).
    "loggers": {"httpx": {"level": "WARNING"}, "httpcore": {"level": "WARNING"}},
}
