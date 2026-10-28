"""`/health`: 200 with a database connection, with the number of tenants
loaded and degraded; 503 without it. No external calls, and no names: it is public."""

from django.db import Error as DatabaseError
from django.db import connections
from django.http import HttpRequest, JsonResponse
from django.views.decorators.http import require_GET

from autobot.tenancy.registry import get_registry


@require_GET
def health(request: HttpRequest) -> JsonResponse:
    registry = get_registry()
    tenants = {
        "loaded": len(registry.tenants),
        "degraded": sum(t.is_degraded for t in registry.tenants),
        "unreadable": len(registry.errors),
    }
    try:
        with connections["default"].cursor() as cursor:
            cursor.execute("SELECT 1")
    except DatabaseError:
        return JsonResponse({"status": "error", "database": False, "tenants": tenants}, status=503)
    return JsonResponse({"status": "ok", "database": True, "tenants": tenants})
