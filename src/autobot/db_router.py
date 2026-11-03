"""Routes Django's own auth/session/OTP models to `owner` (fp_owner, BYPASSRLS):
these are platform tables with no tenant data, and `fp_app` loses direct access to
them entirely (db_grants.py). Everything else keeps the default (`default`, fp_app)."""

from typing import Any

from django.conf import settings
from django.db.models import Model

AUTH_APP_LABELS = frozenset({"auth", "contenttypes", "sessions", "otp_totp", "django_otp"})


class AuthDatabaseRouter:
    def _owner_or_none(self, model: type[Model]) -> str | None:
        if model._meta.app_label in AUTH_APP_LABELS:
            return "owner" if "owner" in settings.DATABASES else None
        return None

    def db_for_read(self, model: type[Model], **hints: Any) -> str | None:
        return self._owner_or_none(model)

    def db_for_write(self, model: type[Model], **hints: Any) -> str | None:
        return self._owner_or_none(model)

    def allow_relation(self, obj1: Any, obj2: Any, **hints: Any) -> bool | None:
        labels = {obj1._meta.app_label, obj2._meta.app_label}
        return True if labels <= AUTH_APP_LABELS else None

    def allow_migrate(self, db: str, app_label: str, **hints: Any) -> bool | None:
        return None
