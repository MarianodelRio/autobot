"""Panel authentication: session + confirmed TOTP, CSRF-checked writes.
django-ninja's `APIKeyCookie` already rejects unsafe methods without a valid
`X-CSRFToken`; neither class below repeats that check."""

from typing import Any

from django.conf import settings
from django.contrib.auth import authenticate
from django.contrib.auth import login as django_login
from django.contrib.auth import logout as django_logout
from django.core.cache import cache
from django.db import transaction
from django.http import HttpRequest
from django.middleware.csrf import get_token
from django_otp import login as otp_login  # type: ignore[import-untyped]
from django_otp.plugins.otp_totp.models import TOTPDevice  # type: ignore[import-untyped]
from ninja import Router, Schema
from ninja.errors import HttpError
from ninja.security import APIKeyCookie

from autobot.ops import audit

LOCKOUT_THRESHOLD = 5
LOCKOUT_WINDOW_S = 15 * 60
GENERIC_ERROR = "Credenciales no válidas."


class PanelAuth(APIKeyCookie):
    """Every route but `auth/csrf` and `auth/login` requires a verified session."""

    param_name = settings.SESSION_COOKIE_NAME

    def authenticate(self, request: HttpRequest, key: str | None) -> Any:
        user = request.user
        if user.is_authenticated and user.is_staff and user.is_verified():  # type: ignore[attr-defined]
            return user
        return None


class CsrfOnly(APIKeyCookie):
    """`auth/login` has no session yet: only the CSRF check (done by the base class)."""

    param_name = settings.SESSION_COOKIE_NAME

    def authenticate(self, request: HttpRequest, key: str | None) -> Any:
        return True


router = Router(tags=["auth"])


@router.get("/csrf", auth=None)
def csrf(request: HttpRequest) -> dict[str, bool]:
    get_token(request)  # forces the cookie to be sent
    return {"ok": True}


class LoginIn(Schema):
    username: str
    password: str
    otp: str


class MeOut(Schema):
    username: str


def _lockout_key(username: str) -> str:
    return f"panel:login:{username}"


@router.post("/login", auth=CsrfOnly())
def login(request: HttpRequest, payload: LoginIn) -> MeOut:
    username = payload.username[:150]
    lockout_key = _lockout_key(username)
    if (cache.get(lockout_key) or 0) >= LOCKOUT_THRESHOLD:
        audit.record(
            actor=username, action="auth.login_failed", summary=f"Login bloqueado: {username}"
        )
        raise HttpError(401, GENERIC_ERROR)
    # Raising inside the atomic block would roll back the audit row and the device's
    # own throttle bookkeeping along with it: decide here, act on it once outside.
    failed = True
    with transaction.atomic(using="owner"):
        user = authenticate(request, username=payload.username, password=payload.password)
        device = None
        if user is not None:
            device = (
                TOTPDevice.objects.filter(user=user, confirmed=True).select_for_update().first()
            )
        if user is not None and device is not None and device.verify_token(payload.otp):
            failed = False
            django_login(request, user)
            otp_login(request, device)
    if failed:
        cache.set(lockout_key, (cache.get(lockout_key) or 0) + 1, timeout=LOCKOUT_WINDOW_S)
        audit.record(
            actor=username, action="auth.login_failed", summary=f"Login fallido: {username}"
        )
        raise HttpError(401, GENERIC_ERROR)
    cache.delete(lockout_key)
    audit.record(actor=username, action="auth.login", summary=f"Login: {username}")
    assert user is not None
    return MeOut(username=user.username)


@router.post("/logout", auth=PanelAuth())
def logout(request: HttpRequest) -> dict[str, bool]:
    django_logout(request)
    return {"ok": True}


@router.get("/me", auth=PanelAuth())
def me(request: HttpRequest) -> MeOut:
    return MeOut(username=request.user.username)
