"""Step-up reauthentication: destructive or sensitive panel actions need a TOTP code
entered within the last `REAUTH_MAX_AGE_S` seconds (`POST auth/step-up` records it in
the session as `panel_reauth_at`). Routes opt in with `@require_recent_reauth`."""

import functools
import time
from collections.abc import Callable
from typing import Any, ParamSpec, TypeVar

from django.http import HttpRequest

from autobot.panel.errors import ApiError

REAUTH_SESSION_KEY = "panel_reauth_at"
REAUTH_MAX_AGE_S = 5 * 60

P = ParamSpec("P")
R = TypeVar("R")


def mark_reauthenticated(request: HttpRequest) -> None:
    request.session[REAUTH_SESSION_KEY] = time.time()


def has_recent_reauth(request: HttpRequest, max_age: int = REAUTH_MAX_AGE_S) -> bool:
    at: Any = request.session.get(REAUTH_SESSION_KEY)
    if not isinstance(at, int | float):
        return False
    age = time.time() - at
    return 0 <= age <= max_age


def reauth_required() -> ApiError:
    return ApiError("reauth_required", "Esta acción requiere confirmar tu código TOTP.", 403)


def require_recent_reauth(
    max_age: int = REAUTH_MAX_AGE_S,
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Decorator for a ninja view (place it below the `@router.*` line); the first
    argument must be the request. Answers 403 `reauth_required` when the session has no
    step-up or it is older than `max_age` seconds."""

    def decorator(view: Callable[P, R]) -> Callable[P, R]:
        @functools.wraps(view)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            request: HttpRequest = args[0]  # type: ignore[assignment]
            if not has_recent_reauth(request, max_age):
                raise reauth_required()
            return view(*args, **kwargs)

        return wrapper

    return decorator
