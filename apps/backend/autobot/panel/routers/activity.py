"""Readable cross-tenant activity feed."""

from django.http import HttpRequest
from ninja import Router

from autobot.panel.services.activity import ActivityPage, activity_page

router = Router(tags=["activity"])


@router.get("/activity", response=ActivityPage)
def activity(
    request: HttpRequest,
    tenant: str = "",
    kinds: str = "",
    status: str = "",
    cursor: str = "",
    limit: int = 50,
) -> ActivityPage:
    limit = max(1, min(limit, 100))
    return activity_page(tenant=tenant, kinds=kinds, status=status, cursor=cursor, limit=limit)
