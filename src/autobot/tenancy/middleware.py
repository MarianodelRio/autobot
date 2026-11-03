"""Pin the tenant registry for the duration of each request."""

from collections.abc import Callable

from django.http import HttpRequest, HttpResponse

from autobot.tenancy.registry import registry_scope


class RegistryScopeMiddleware:
    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        with registry_scope():
            return self.get_response(request)
