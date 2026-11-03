"""PanelGateMiddleware (DESIGN §3.2, point 5): keeps `/api/panel/` unreachable from the
public edge, and inert on a process without the `owner` alias. Runs before
`SessionMiddleware`, so a request that fails here never touches the session."""

from collections.abc import Callable
from typing import Any

from django.conf import settings
from django.http import HttpResponse

PREFIX = "/api/panel/"


class PanelGateMiddleware:
    def __init__(self, get_response: Callable[[Any], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: Any) -> HttpResponse:
        if request.path.startswith(PREFIX):
            # Caddy's public edge sets this on everything it forwards (Caddyfile);
            # only the panel's own proxy reaches here without it.
            if request.headers.get("X-Autobot-Edge"):
                return HttpResponse(status=404)
            if "owner" not in settings.DATABASES:
                return HttpResponse(status=503)
        return self.get_response(request)
