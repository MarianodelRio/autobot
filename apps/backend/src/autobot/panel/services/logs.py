"""Bounded LogsQL queries, checked against VictoriaLogs v1.53.0 docs.

References (pinned to the compose image's tag):
https://github.com/VictoriaMetrics/VictoriaLogs/blob/v1.53.0/docs/victorialogs/logsql.md
https://github.com/VictoriaMetrics/VictoriaLogs/blob/v1.53.0/docs/victorialogs/querying/README.md
"""

import contextlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import httpx
from django.conf import settings
from django.utils import timezone
from ninja import Schema

from autobot.panel.errors import ApiError
from autobot.tenancy.models import Tenant


class LogFilters(Schema):
    tenant: str = ""
    level: str = ""
    service: str = ""
    q: str = ""
    start: datetime | None = None
    end: datetime | None = None
    limit: int = 200


class LogsOut(Schema):
    items: list[dict[str, Any]]
    truncated: bool
    clipped: bool


def quote(value: str) -> str:
    # JSON double-quoted strings use the same escaping as LogsQL, also for control chars.
    return json.dumps(value, ensure_ascii=False)


def prepare(filters: LogFilters) -> tuple[LogFilters, bool]:
    now = timezone.now()
    boundary = now - timedelta(days=31)
    end = filters.end or now
    start = filters.start or end - timedelta(hours=1)
    if start.utcoffset() is None or end.utcoffset() is None:
        raise ApiError("bad_request", "Las fechas deben incluir la zona horaria.", 400)
    if start > end or filters.limit < 1:
        raise ApiError("bad_request", "Rango o límite no válido.", 400)
    clipped = start < boundary
    return filters.model_copy(
        update={"start": max(start, boundary), "end": end, "limit": min(filters.limit, 1000)}
    ), clipped


def build_query(filters: LogFilters) -> str:
    filters, _ = prepare(filters)
    assert filters.start is not None and filters.end is not None
    start = filters.start.astimezone(UTC).isoformat()
    end = filters.end.astimezone(UTC).isoformat()
    parts = [f"_time:[{quote(start)}, {quote(end)}]"]
    for field in ("level", "service"):
        value = getattr(filters, field)
        if value:
            parts.append(f"{field}:={quote(value)}")
    if filters.tenant:
        tenant = Tenant.objects.using("owner").filter(slug=filters.tenant).first()
        if tenant is None:
            with contextlib.suppress(ValueError):
                tenant = Tenant.objects.using("owner").filter(pk=UUID(filters.tenant)).first()
        values = [filters.tenant] if tenant is None else [tenant.slug, str(tenant.id)]
        parts.append("(" + " OR ".join(f"tenant:={quote(value)}" for value in values) + ")")
    if filters.q:
        parts.append("_msg:" + quote(filters.q))
    return " AND ".join(parts) + f" | sort by (_time) desc | limit {filters.limit + 1}"


def query_logs(filters: LogFilters) -> LogsOut:
    prepared, clipped = prepare(filters)
    # An entirely expired range is empty; never query an inverted time range.
    assert prepared.start is not None and prepared.end is not None
    if prepared.end < prepared.start:
        return LogsOut(items=[], truncated=False, clipped=clipped)
    url = settings.VICTORIALOGS_URL
    if not url:
        raise ApiError("logs_unavailable", "El servicio de logs no está disponible.", 503)
    try:
        with (
            httpx.Client(timeout=10.0) as client,
            client.stream(
                "GET",
                url.rstrip("/") + "/select/logsql/query",
                params={"query": build_query(prepared)},
            ) as response,
        ):
            response.raise_for_status()
            items = []
            for line in response.iter_lines():
                if not line.strip():
                    continue
                item = json.loads(line)
                if not isinstance(item, dict):
                    raise ValueError("Invalid log row")
                items.append(item)
                if len(items) > prepared.limit:
                    break
    except httpx.HTTPError, ValueError, UnicodeError:
        raise ApiError("logs_unavailable", "El servicio de logs no está disponible.", 503) from None
    slugs = {str(id): slug for id, slug in Tenant.objects.using("owner").values_list("id", "slug")}
    for item in items[: prepared.limit]:
        tenant_value = item.get("tenant")
        if isinstance(tenant_value, str):
            item["tenant"] = slugs.get(tenant_value, tenant_value)
    return LogsOut(
        items=items[: prepared.limit], truncated=len(items) > prepared.limit, clipped=clipped
    )
