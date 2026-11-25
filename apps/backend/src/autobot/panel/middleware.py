"""PanelGateMiddleware (ADR-008): keeps `/api/panel/` unreachable from the
public edge, and inert on a process without the `owner` alias. Runs before
`SessionMiddleware`, so a request that fails here never touches the session."""

import logging
from collections.abc import Callable
from typing import Any

from django.conf import settings
from django.http import HttpResponse

from autobot.tenancy.registry import get_registry

log = logging.getLogger(__name__)

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


class PanelFreshConfigMiddleware:
    """Every panel request starts from the configuration as it is in the database now
    (ADR-030): one revision check, and if another process wrote since this one last
    looked, an incremental reload before the request runs, whose snapshot the request
    then keeps (`RegistryScopeMiddleware` pinned the scope). Without it a request landing
    on a gunicorn worker that has not polled yet would show the data from before a save
    made through another worker. It waits for the reload because the panel is
    authenticated, reachable only through the tunnel, and the reload is incremental;
    public paths (webhooks) never come here. Runs after `PanelGateMiddleware`, so what the
    gate refuses never reaches the database."""

    def __init__(self, get_response: Callable[[Any], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: Any) -> HttpResponse:
        if request.path.startswith(PREFIX):
            try:
                get_registry(force=True)
            except Exception:
                # Login and the health of the panel do not need the registry: whoever
                # does will raise the same error itself.
                log.warning("Fresh config check before a panel request failed", exc_info=True)
        return self.get_response(request)
