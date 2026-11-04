"""Unified API error shape (DESIGN §6.3): `{"code", "message", "details"}`."""


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
    "unavailable": 503,
    "logs_unavailable": 503,
}
