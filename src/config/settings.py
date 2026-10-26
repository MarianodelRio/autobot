"""Django settings, read from environment variables.

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
    "django_otp",
    "django_otp.plugins.otp_totp",
    "flowpilot",
]
# Development-only: provides `lintmigrations` for CI; absent from the image.
if importlib.util.find_spec("django_migration_linter"):
    INSTALLED_APPS.append("django_migration_linter")
    # Third-party migrations are not ours to fix; every app of ours is linted.
    MIGRATION_LINTER_OPTIONS = {
        "exclude_apps": ["procrastinate", "otp_totp"],
        # Drops the retired test-bot tables: approved by the person (2026-10-26,
        # docs/mejoras/01-bot-de-demo.md §2).
        "ignore_name": ["0008_demo_channels"],
    }

DATABASE_ROUTERS = ["flowpilot.admin_db.AdminDatabaseRouter"]

MIDDLEWARE = [
    "flowpilot.admin_db.AdminDatabaseMiddleware",
    "flowpilot.ops.logging.LogContextMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django_otp.middleware.OTPMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
if not IS_LOCAL:
    MIDDLEWARE.insert(3, "whitenoise.middleware.WhiteNoiseMiddleware")

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


# Two aliases: `default` is fp_app (no BYPASSRLS, no DDL), used by web
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

# Job queue: Procrastinate on the `default` alias (fp_app); jobs are
# declared in flowpilot/jobs.py.
PROCRASTINATE_AUTODISCOVER_MODULE_NAME = "jobs"

# Tenants: config in git, channel secrets on the server (in local, the
# repository root, ignored by git).
TENANTS_DIR = Path(os.environ.get("TENANTS_DIR", BASE_DIR / "tenants"))
SECRETS_FILE = Path(env("SECRETS_FILE", str(BASE_DIR / "secrets.yaml")))

# Channels. Graph API version of the WhatsApp Cloud API (reviewed every six
# months).
WHATSAPP_GRAPH_VERSION = env("WHATSAPP_GRAPH_VERSION", "v23.0")


def _ids(name: str) -> frozenset[int]:
    raw = os.environ.get(name, "")
    try:
        return frozenset(int(part) for part in raw.replace(",", " ").split())
    except ValueError:
        raise ImproperlyConfigured(f"{name} must be Telegram user ids") from None


# The platform's demo bot, Telegram door. Without a token it is off; without a webhook
# secret its webhook is off (local development uses `telegram_poll`).
DEMO_TELEGRAM_TOKEN = os.environ.get("DEMO_TELEGRAM_TOKEN", "")
DEMO_TELEGRAM_WEBHOOK_SECRET = os.environ.get("DEMO_TELEGRAM_WEBHOOK_SECRET", "")
if DEMO_TELEGRAM_WEBHOOK_SECRET and len(DEMO_TELEGRAM_WEBHOOK_SECRET) < 32:
    raise ImproperlyConfigured("DEMO_TELEGRAM_WEBHOOK_SECRET must have 32 characters or more")
DEMO_TELEGRAM_USERS = _ids("DEMO_TELEGRAM_USERS")  # closed list of this door

# Public base of the webhooks (https://api.<dominio>), for `telegram_set_webhook`.
PUBLIC_URL = os.environ.get("PUBLIC_URL", "")

LANGUAGE_CODE = "es-es"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"
        if not IS_LOCAL
        else "django.contrib.staticfiles.storage.StaticFilesStorage"
    }
}

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {"privacy": {"()": "flowpilot.ops.logging.PrivacyFilter"}},
    "formatters": {"json": {"()": "flowpilot.ops.logging.JsonFormatter"}},
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "stream": "ext://sys.stdout",
            "formatter": "json",
            "filters": ["privacy"],
        }
    },
    "root": {"handlers": ["console"], "level": os.environ.get("LOG_LEVEL", "INFO")},
    # httpx logs every request URL at INFO, and Telegram's carries the bot token.
    "loggers": {"httpx": {"level": "WARNING"}, "httpcore": {"level": "WARNING"}},
}

GOOGLE_SERVICE_ACCOUNT_FILE = os.environ.get("GOOGLE_SERVICE_ACCOUNT_FILE", "")

# Outbound-only notification bot; unconfigured locally until it is created.
NOTIFY_BOT_TOKEN = os.environ.get("NOTIFY_BOT_TOKEN", "")
OPS_TELEGRAM_CHAT_ID = os.environ.get("OPS_TELEGRAM_CHAT_ID", "")
CACHES = {
    "default": {
        "BACKEND": "flowpilot.cache.CooldownCache",
        "LOCATION": "platform_cache",
    }
}


HEALTHCHECKS_PING_URL = os.environ.get("HEALTHCHECKS_PING_URL", "")
SENTRY_DSN = os.environ.get("SENTRY_DSN", "")
RELEASE_SHA = os.environ.get("RELEASE_SHA", os.environ.get("SHA", ""))
SERVICE_NAME = os.environ.get("SERVICE_NAME", "web")

# Explicit human approval is required before enabling destructive periodic retention.
RETENTION_CLEANUP_ENABLED = os.environ.get("RETENTION_CLEANUP_ENABLED", "false").lower() == "true"
