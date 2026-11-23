"""Django settings, read from environment variables.

`ENVIRONMENT=local` provides development defaults; `ENVIRONMENT=prod` requires every
secret to be set explicitly. When `ENVIRONMENT` is unset the environment is `prod`
(fail closed): local tools and tests use `config.settings_dev`, which sets it to `local`.
"""

import importlib.util
import os
from pathlib import Path
from typing import Any

import dj_database_url
from cryptography.fernet import Fernet
from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent

ENVIRONMENT = os.environ.get("ENVIRONMENT") or "prod"
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


# Values published as examples in .env.example: a prod .env that still has them is
# unconfigured, not merely insecure by the human's own choice.
_EXAMPLE_SECRET_KEY = "change-me"
_EXAMPLE_ENCRYPTION_KEY = "UHx17yr1uv1SdskJ5dGpF1MYUPfD2ierqd5mY_2AQ_w="

SECRET_KEY = env("DJANGO_SECRET_KEY", "local-insecure-secret-key")
SECRETS_ENCRYPTION_KEYS: list[str] = [
    key.strip() for key in env("SECRETS_ENCRYPTION_KEY", _EXAMPLE_ENCRYPTION_KEY).split(",")
]
if not IS_LOCAL:
    if SECRET_KEY == _EXAMPLE_SECRET_KEY:
        raise ImproperlyConfigured("DJANGO_SECRET_KEY must not be the .env.example value")
    if _EXAMPLE_ENCRYPTION_KEY in SECRETS_ENCRYPTION_KEYS:
        raise ImproperlyConfigured("SECRETS_ENCRYPTION_KEY must not be the .env.example value")
    try:
        for key in SECRETS_ENCRYPTION_KEYS:
            Fernet(key)
    except ValueError, TypeError:
        raise ImproperlyConfigured(
            "SECRETS_ENCRYPTION_KEY must contain valid Fernet keys"
        ) from None

DEBUG = IS_LOCAL
_hosts = env("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")
ALLOWED_HOSTS = [h.strip() for h in _hosts.split(",") if h.strip()]

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "procrastinate.contrib.django",
    "django_otp",
    "django_otp.plugins.otp_totp",
    "autobot",
]
# Development-only: provides `lintmigrations` for CI; absent from the image.
if importlib.util.find_spec("django_migration_linter"):
    INSTALLED_APPS.append("django_migration_linter")
    # Third-party migrations are not ours to fix; every app of ours is linted.
    MIGRATION_LINTER_OPTIONS = {
        "exclude_apps": ["procrastinate", "otp_totp"],
    }

MIDDLEWARE = [
    "autobot.ops.logging.LogContextMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "autobot.tenancy.middleware.RegistryScopeMiddleware",
    "autobot.panel.middleware.PanelGateMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django_otp.middleware.OTPMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
DATABASE_ROUTERS = ["autobot.db.router.AuthDatabaseRouter"]


# Three aliases: `default` is fp_app (no BYPASSRLS, no DDL), used by web and worker;
# `owner` is fp_owner (owns the tables, BYPASSRLS), used only by migrations, operation
# commands and the panel; `readonly` is fp_readonly (NOBYPASSRLS, SELECT only),
# used only by the panel's SQL console, with CONN_MAX_AGE=0 so nothing from a query
# survives the connection. The worker runs without DB_OWNER_URL or DB_READONLY_URL, so
# without those aliases. Local defaults match compose.yaml, whose db is published on
# port 5433.
CONN_MAX_AGE = int(os.environ.get("DB_CONN_MAX_AGE", "60"))


def _database(url: str, conn_max_age: int = CONN_MAX_AGE) -> dict[str, Any]:
    return dict(dj_database_url.parse(url, conn_max_age=conn_max_age, conn_health_checks=True))


def _reject_example_db_url(name: str, url: str) -> None:
    if not IS_LOCAL and "localhost" in url:
        raise ImproperlyConfigured(f"{name} must not point to localhost in prod")


_app_url = env("DB_APP_URL", "postgres://fp_app:fp_app@localhost:5433/autobot")
_reject_example_db_url("DB_APP_URL", _app_url)
DATABASES = {
    "default": _database(_app_url),
}
# Unset → local default; set but empty (the worker) → no `owner`/`readonly` alias.
_owner_url = os.environ.get(
    "DB_OWNER_URL", "postgres://fp_owner:fp_owner@localhost:5433/autobot" if IS_LOCAL else ""
)
if _owner_url:
    _reject_example_db_url("DB_OWNER_URL", _owner_url)
    DATABASES["owner"] = _database(_owner_url)
_readonly_url = os.environ.get(
    "DB_READONLY_URL",
    "postgres://fp_readonly:fp_readonly@localhost:5433/autobot" if IS_LOCAL else "",
)
if _readonly_url:
    _reject_example_db_url("DB_READONLY_URL", _readonly_url)
    DATABASES["readonly"] = _database(_readonly_url, conn_max_age=0)

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 12},
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
OTP_TOTP_ISSUER = "Autobot panel"

# The panel's session: traffic stays on the SSH tunnel to 127.0.0.1
# (ADR-008), so there is no TLS between the browser and `panel` to require Secure.
SESSION_COOKIE_NAME = "autobot_panel_session"
CSRF_COOKIE_NAME = "autobot_panel_csrftoken"
SESSION_COOKIE_AGE = 12 * 3600
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Strict"
CSRF_COOKIE_SAMESITE = "Strict"
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False

# Job queue: Procrastinate on the `default` alias (fp_app); jobs are
# declared in autobot/runtime/jobs.py.
PROCRASTINATE_AUTODISCOVER_MODULE_NAME = "runtime.jobs"
# `procrastinate worker` uses its own psycopg pool (4 connections by default, never
# shrinking): bounded here, with room for the LISTEN connection, fetch, heartbeat and
# the finish of `--concurrency` jobs (autobot/runtime/worker_pool.py).
PROCRASTINATE_ON_APP_READY = "autobot.runtime.worker_pool.configure"
WORKER_DB_POOL_MIN = int(os.environ.get("WORKER_DB_POOL_MIN", "1"))
WORKER_DB_POOL_MAX = int(os.environ.get("WORKER_DB_POOL_MAX", "6"))

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
# Informational, like DEMO_WHATSAPP_DISPLAY_PHONE: lets the panel build a
# `t.me/<username>?start=<code>` invite link for this door's QR. Without it, an
# invite still works, but the panel can only show its bare code.
DEMO_TELEGRAM_BOT_USERNAME = os.environ.get("DEMO_TELEGRAM_BOT_USERNAME", "")


def _strings(name: str) -> frozenset[str]:
    return frozenset(part.strip() for part in os.environ.get(name, "").split(",") if part.strip())


# The platform's demo bot, WhatsApp door. Off unless every Meta id and secret below is
# set (channels/demo/doors.py).
DEMO_WHATSAPP_PHONE_NUMBER_ID = os.environ.get("DEMO_WHATSAPP_PHONE_NUMBER_ID", "")
DEMO_WHATSAPP_WABA_ID = os.environ.get("DEMO_WHATSAPP_WABA_ID", "")
DEMO_WHATSAPP_DISPLAY_PHONE = os.environ.get("DEMO_WHATSAPP_DISPLAY_PHONE", "")  # informational
DEMO_WHATSAPP_APP_SECRET = os.environ.get("DEMO_WHATSAPP_APP_SECRET", "")
DEMO_WHATSAPP_ACCESS_TOKEN = os.environ.get("DEMO_WHATSAPP_ACCESS_TOKEN", "")
DEMO_WHATSAPP_VERIFY_TOKEN = os.environ.get("DEMO_WHATSAPP_VERIFY_TOKEN", "")
DEMO_WHATSAPP_USERS = _strings("DEMO_WHATSAPP_USERS")  # closed list: phones or BSUIDs
try:
    DEMO_WHATSAPP_MONTHLY_ALERT_THRESHOLD = int(
        os.environ.get("DEMO_WHATSAPP_MONTHLY_ALERT_THRESHOLD", "300")
    )
except ValueError:
    raise ImproperlyConfigured("DEMO_WHATSAPP_MONTHLY_ALERT_THRESHOLD must be an integer") from None
if DEMO_WHATSAPP_MONTHLY_ALERT_THRESHOLD <= 0:
    raise ImproperlyConfigured("DEMO_WHATSAPP_MONTHLY_ALERT_THRESHOLD must be positive")

# Public base of the webhooks (https://api.<dominio>), for `telegram_set_webhook`.
PUBLIC_URL = os.environ.get("PUBLIC_URL", "")

# Google Calendar used by the salon pack's demo business, applied by `seed_demos`
# over the template's placeholder (docs/procedimientos/demo.md).
DEMO_SALON_CALENDAR_ID = os.environ.get("DEMO_SALON_CALENDAR_ID", "")

LANGUAGE_CODE = "es-es"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

VICTORIALOGS_URL = os.environ.get("VICTORIALOGS_URL", "")

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {"privacy": {"()": "autobot.ops.logging.PrivacyFilter"}},
    "formatters": {"json": {"()": "autobot.ops.logging.JsonFormatter"}},
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "stream": "ext://sys.stderr"
            if os.environ.get("AUTOBOT_BINARY_STDOUT")
            else "ext://sys.stdout",
            "formatter": "json",
            "filters": ["privacy"],
        },
        **(
            {
                "victorialogs": {
                    "class": "autobot.ops.logship.VictoriaLogsHandler",
                    "url": VICTORIALOGS_URL,
                    "filters": ["privacy"],
                }
            }
            if VICTORIALOGS_URL
            else {}
        ),
    },
    "root": {
        "handlers": ["console", *(["victorialogs"] if VICTORIALOGS_URL else [])],
        "level": os.environ.get("LOG_LEVEL", "INFO"),
    },
    # httpx logs every request URL at INFO, and Telegram's carries the bot token.
    "loggers": {"httpx": {"level": "WARNING"}, "httpcore": {"level": "WARNING"}},
}

GOOGLE_SERVICE_ACCOUNT_FILE = os.environ.get("GOOGLE_SERVICE_ACCOUNT_FILE", "")

# The platform's one notify bot, also the owner's small assistant (inbound since
# ADR-007): unconfigured locally until it is created.
NOTIFY_BOT_TOKEN = os.environ.get("NOTIFY_BOT_TOKEN", "")
NOTIFY_BOT_WEBHOOK_SECRET = os.environ.get("NOTIFY_BOT_WEBHOOK_SECRET", "")
if NOTIFY_BOT_WEBHOOK_SECRET and len(NOTIFY_BOT_WEBHOOK_SECRET) < 32:
    raise ImproperlyConfigured("NOTIFY_BOT_WEBHOOK_SECRET must have 32 characters or more")
OWNER_SUPPORT_EMAIL = os.environ.get("OWNER_SUPPORT_EMAIL", "")
OPS_TELEGRAM_CHAT_ID = os.environ.get("OPS_TELEGRAM_CHAT_ID", "")
# Privacy policy of the platform, cited by the demo bot's first-contact notice (the
# platform is the controller there). Optional: without it the notice omits the link.
PLATFORM_PRIVACY_URL = os.environ.get("PLATFORM_PRIVACY_URL", "")
if PLATFORM_PRIVACY_URL and not PLATFORM_PRIVACY_URL.startswith("https://"):
    raise ImproperlyConfigured("PLATFORM_PRIVACY_URL must start with https://")
CACHES = {
    "default": {
        "BACKEND": "autobot.runtime.cache.CooldownCache",
        "LOCATION": "platform_cache",
    }
}


OPS_STATE_DIR = Path(os.environ.get("OPS_STATE_DIR", BASE_DIR / "state" / "ops"))
HEALTHCHECKS_PING_URL = os.environ.get("HEALTHCHECKS_PING_URL", "")
SENTRY_DSN = os.environ.get("SENTRY_DSN", "")
RELEASE_SHA = os.environ.get("RELEASE_SHA", os.environ.get("SHA", ""))
SERVICE_NAME = os.environ.get("SERVICE_NAME", "web")

# Destructive periodic retention: off unless the environment says so. compose.prod.yaml
# turns it on for production (approved by the person, 2026-11-23); local stays off.
RETENTION_CLEANUP_ENABLED = os.environ.get("RETENTION_CLEANUP_ENABLED", "false").lower() == "true"
