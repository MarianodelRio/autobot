"""`/health`: a public liveness probe (200 while the process answers), without touching
the database nor revealing anything, since Caddy forwards it to anyone on the internet.
`/health/internal` carries the database state and the number of tenants loaded and
degraded that `deploy.sh` needs: Caddy never forwards it (not in its `@public`
matcher) and, like the panel (`PanelGateMiddleware`), it answers 404 to anything that
arrives with the `X-Autobot-Edge` header, i.e. through the edge. No external calls, and
no names, on either route."""

from django.db import Error as DatabaseError
from django.db import connections
from django.http import Http404, HttpRequest, JsonResponse
from django.views.decorators.http import require_GET

from autobot.tenancy.registry import get_registry

EDGE_HEADER = "X-Autobot-Edge"


def _status() -> tuple[bool, dict[str, int]]:
    tenants = {"loaded": 0, "degraded": 0, "unreadable": 0}
    try:
        registry = get_registry()
        tenants = {
            "loaded": len(registry.tenants),
            "degraded": sum(t.is_degraded for t in registry.tenants),
            "unreadable": len(registry.errors),
        }
        with connections["default"].cursor() as cursor:
            cursor.execute("SELECT 1")
    except DatabaseError:
        return False, tenants
    return True, tenants


@require_GET
def health(request: HttpRequest) -> JsonResponse:
    return JsonResponse({"status": "ok"})


@require_GET
def health_internal(request: HttpRequest) -> JsonResponse:
    if EDGE_HEADER in request.headers:
        raise Http404
    ok, tenants = _status()
    body = {"status": "ok" if ok else "error", "database": ok, "tenants": tenants}
    return JsonResponse(body, status=200 if ok else 503)
