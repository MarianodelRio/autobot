"""Panel authentication: session + confirmed TOTP, CSRF-checked writes.
django-ninja's `APIKeyCookie` already rejects unsafe methods without a valid
`X-CSRFToken`; neither class below repeats that check."""

import hashlib
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

from autobot.channels.ratelimit import client_ip
from autobot.ops import audit

LOCKOUT_THRESHOLD = 5
IP_LOCKOUT_THRESHOLD = 20  # one address may try several usernames
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


def _slot_keys(scope: str, subject: str, limit: int) -> list[str]:
    digest = hashlib.sha256(subject.lower().encode()).hexdigest()[:32]
    return [f"panel:login:{scope}:{digest}:{i}" for i in range(limit)]


def _take_slot(keys: list[str]) -> str | None:
    """Reserves one attempt before it is checked. `cache.add` is atomic (a unique key),
    unlike a read-then-write counter, so concurrent guesses each take a distinct slot
    and cannot slip past the limit together. `None`: no slot left, locked out."""
    for key in keys:
        if cache.add(key, 1, timeout=LOCKOUT_WINDOW_S):
            return key
    return None


def _blocked(username: str, scope: str) -> HttpError:
    audit.record(
        actor=username,
        action="auth.login_blocked",
        summary=f"Login bloqueado ({scope}): {username}",
        details={"scope": scope},
    )
    return HttpError(401, GENERIC_ERROR)


@router.post("/login", auth=CsrfOnly())
def login(request: HttpRequest, payload: LoginIn) -> MeOut:
    username = payload.username[:150]
    user_keys = _slot_keys("user", username, LOCKOUT_THRESHOLD)
    ip_keys = _slot_keys("ip", client_ip(request), IP_LOCKOUT_THRESHOLD)
    ip_slot = _take_slot(ip_keys)
    if ip_slot is None:
        raise _blocked(username, "ip")
    if _take_slot(user_keys) is None:
        cache.delete(ip_slot)  # a locked-out user's attempt does not also burn the IP's
        raise _blocked(username, "user")
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
        audit.record(
            actor=username, action="auth.login_failed", summary=f"Login fallido: {username}"
        )
        raise HttpError(401, GENERIC_ERROR)
    cache.delete_many([*user_keys, ip_slot])
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
