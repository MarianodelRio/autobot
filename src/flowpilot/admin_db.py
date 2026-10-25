"""Owner routing is confined to internal Admin requests, including session responses."""

from collections.abc import Callable
from contextvars import ContextVar
from typing import Any

from django.conf import settings
from django.http import HttpRequest, HttpResponse

admin_request: ContextVar[bool] = ContextVar("admin_request", default=False)


class AdminDatabaseMiddleware:
    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        internal = request.path_info == "/admin" or request.path_info.startswith("/admin/")
        if internal and "owner" not in settings.DATABASES:
            return HttpResponse("Administración no disponible.", status=503)
        token = admin_request.set(internal)
        try:
            return self.get_response(request)
        finally:
            admin_request.reset(token)


class AdminDatabaseRouter:
    def db_for_read(self, model: Any, **hints: Any) -> str | None:
        return "owner" if admin_request.get() else None

    def db_for_write(self, model: Any, **hints: Any) -> str | None:
        return "owner" if admin_request.get() else None
