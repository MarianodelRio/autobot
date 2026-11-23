"""Audited operations history (keyset pagination in `services/pagination.py`)."""

from datetime import datetime
from typing import Any
from uuid import UUID

from django.http import HttpRequest
from ninja import Router, Schema

from autobot.ops.audit import distinct_actions
from autobot.ops.models import AuditEvent
from autobot.panel.services.pagination import page
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


@router.get("/audit/actions", response=list[str])
def audit_actions(request: HttpRequest) -> list[str]:
    return distinct_actions()


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
    # Only the tenants this page mentions, not every tenant of the platform.
    slugs = {
        str(id): slug
        for id, slug in Tenant.objects.using("owner")
        .filter(id__in={r.tenant_id for r in rows if r.tenant_id})
        .values_list("id", "slug")
    }
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
