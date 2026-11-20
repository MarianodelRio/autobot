"""Unified API error shape: `{"code", "message", "details"}`."""

from django.http import Http404, HttpRequest
from ninja import Router


class ApiError(Exception):
    def __init__(
        self, code: str, message: str, status: int, details: list[str] | None = None
    ) -> None:
        self.code = code
        self.message = message
        self.status = status
        self.details = details or []
        super().__init__(message)


# StoreError (autobot.tenancy.store) carries one of these codes; this is the HTTP
# status each maps to.
CODE_STATUS: dict[str, int] = {
    "validation_error": 422,
    "conflict": 409,
    "not_found": 404,
    "forbidden_change": 400,
    "invalid_status": 400,
    "bad_request": 400,
    "unauthorized": 401,
    "csrf": 403,
    "too_large": 413,
    "busy": 429,
    "unavailable": 503,
    "logs_unavailable": 503,
}


# Any `/api/panel/*` path nothing else matched: a JSON 404 (via the API's Http404
# handler) instead of Django's HTML page, which in local mode lists every URL.
router = Router()


@router.api_operation(
    ["GET", "POST", "PUT", "PATCH", "DELETE"], "/{path:rest}", include_in_schema=False
)
def unknown_route(request: HttpRequest, rest: str) -> None:
    raise Http404


@router.api_operation(["GET", "POST", "PUT", "PATCH", "DELETE"], "/", include_in_schema=False)
def unknown_root(request: HttpRequest) -> None:
    raise Http404
