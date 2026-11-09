"""Audited operations history and shared (at, id) pagination."""

import base64
import json
from datetime import datetime
from typing import Any
from uuid import UUID

from django.db.models import Q
from django.http import HttpRequest
from django.utils.dateparse import parse_datetime
from ninja import Router, Schema

from autobot.ops.models import AuditEvent
from autobot.panel.errors import ApiError
from autobot.tenancy.models import Tenant

router = Router(tags=["audit"])


class AuditEventOut(Schema):
    id: str
    at: datetime
    actor: str
    action: str
    tenant_id: UUID | None
    tenant: str | None
    target_type: str
    target_id: str
    summary: str
    details: Any


class AuditPage(Schema):
    items: list[AuditEventOut]
    next_cursor: str | None


def position(cursor: str, *, numeric: bool = False) -> tuple[datetime, Any]:
    try:
        data = json.loads(
            base64.b64decode(cursor + "=" * (-len(cursor) % 4), altchars=b"-_", validate=True)
        )
        at = parse_datetime(data["at"])
        id = int(data["id"]) if numeric else UUID(data["id"])
        if at is None or at.utcoffset() is None:
            raise ValueError
        return at, id
    except ValueError, TypeError, KeyError, OverflowError:
        raise ApiError("bad_request", "Cursor no válido.", 400) from None


def page(
    qs: Any, *, field: str, cursor: str, limit: int, numeric: bool = False
) -> tuple[list[Any], str | None]:
    limit = max(1, min(limit, 100))
    if cursor:
        at, id = position(cursor, numeric=numeric)
        qs = qs.filter(Q(**{field + "__lt": at}) | Q(**{field: at, "id__lt": id}))
    rows = list(qs.order_by("-" + field, "-id")[: limit + 1])
    items = rows[:limit]
    next_cursor = None
    if len(rows) > limit:
        last = items[-1]
        data = {"at": getattr(last, field).isoformat(), "id": str(last.pk)}
        next_cursor = base64.urlsafe_b64encode(json.dumps(data).encode()).decode().rstrip("=")
    return items, next_cursor


@router.get("/audit/actions", response=list[str])
def audit_actions(request: HttpRequest) -> list[str]:
    return list(
        AuditEvent.objects.using("owner")
        .order_by("action")
        .values_list("action", flat=True)
        .distinct()
    )


@router.get("/audit", response=AuditPage)
def audit(
    request: HttpRequest, tenant: str = "", action: str = "", cursor: str = "", limit: int = 50
) -> dict[str, Any]:
    qs = AuditEvent.objects.using("owner").all()
    if tenant:
        ids = Tenant.objects.using("owner").filter(slug=tenant).values("id")
        qs = qs.filter(tenant_id__in=ids)
    if action:
        qs = qs.filter(action=action)
    rows, next_cursor = page(qs, field="at", cursor=cursor, limit=limit)
    slugs = {str(id): slug for id, slug in Tenant.objects.using("owner").values_list("id", "slug")}
    return {
        "items": [
            dict(
                id=str(r.id),
                at=r.at,
                actor=r.actor,
                action=r.action,
                tenant_id=r.tenant_id,
                tenant=slugs.get(str(r.tenant_id)) if r.tenant_id else None,
                target_type=r.target_type,
                target_id=r.target_id,
                summary=r.summary,
                details=r.details,
            )
            for r in rows
        ],
        "next_cursor": next_cursor,
    }
