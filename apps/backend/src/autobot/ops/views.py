"""`/health`: 200 with a database connection, 503 without it; no other detail, since
Caddy forwards it to anyone on the internet. `/health/internal` carries the number of
tenants loaded and degraded that `deploy.sh` needs: Caddy never forwards it (not in its
`@public` matcher), so it only answers on the docker network or 127.0.0.1. No external
calls, and no names, on either route."""

from django.db import Error as DatabaseError
from django.db import connections
from django.http import HttpRequest, JsonResponse
from django.views.decorators.http import require_GET

from autobot.tenancy.registry import get_registry


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
    ok, _ = _status()
    return JsonResponse({"status": "ok" if ok else "error"}, status=200 if ok else 503)


@require_GET
def health_internal(request: HttpRequest) -> JsonResponse:
    ok, tenants = _status()
    body = {"status": "ok" if ok else "error", "database": ok, "tenants": tenants}
    return JsonResponse(body, status=200 if ok else 503)
