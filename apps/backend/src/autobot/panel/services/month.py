"""The month-to-date message figures every panel screen needs (Resumen, Clientes, the
ficha), computed in one place so they cannot drift apart. Every query crosses tenants,
so it runs `.using("owner")` explicitly, like the rest of the panel services."""

from collections import defaultdict
from collections.abc import Collection
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from uuid import UUID
from zoneinfo import ZoneInfo

from django.db.models import Count, Q

from autobot.runtime import costs
from autobot.runtime.models import InboundEvent, OutboundMessage

MADRID = ZoneInfo("Europe/Madrid")


@dataclass(frozen=True)
class MonthAggregates:
    """One tenant's figures from `start` on (all zero for a tenant without traffic)."""

    inbound: int = 0
    outbound: int = 0  # messages sent
    users: int = 0  # distinct contacts that were sent something
    billable: int = 0
    pricing_counts: dict[str | None, int] = field(default_factory=dict)

    @property
    def cost_eur(self) -> Decimal:
        return costs.cost_of(self.pricing_counts)


def month_aggregates(tenant_ids: Collection[UUID], start: datetime) -> dict[UUID, MonthAggregates]:
    """The figures of each tenant in `tenant_ids` since `start`, in three queries however
    many tenants there are. Contacts belong to one tenant, so the global figure for
    "users" is just the sum of these."""
    ids = list(tenant_ids)
    inbound = dict(
        InboundEvent.objects.using("owner")
        .filter(tenant_id__in=ids, kind="message", received_at__gte=start)
        .values("tenant_id")
        .annotate(total=Count("id"))
        .values_list("tenant_id", "total")
    )
    sent = Q(status="sent")
    outbound_rows = (
        OutboundMessage.objects.using("owner")
        .filter(tenant_id__in=ids, sent_at__gte=start)
        .order_by()
        .values("tenant_id")
        .annotate(
            sent_total=Count("id", filter=sent),
            users=Count("contact_id", distinct=True, filter=sent),
            billable_total=Count("id", filter=Q(billable=True)),
        )
    )
    outbound = {row["tenant_id"]: row for row in outbound_rows}
    pricing: dict[UUID, dict[str | None, int]] = defaultdict(dict)
    for row in (
        OutboundMessage.objects.using("owner")
        .filter(tenant_id__in=ids, billable=True, sent_at__gte=start)
        .order_by()
        .values("tenant_id", "pricing_category")
        .annotate(total=Count("id"))
    ):
        pricing[row["tenant_id"]][row["pricing_category"]] = row["total"]
    result = {}
    for tenant_id in ids:
        sent_row = outbound.get(tenant_id)
        result[tenant_id] = MonthAggregates(
            inbound=inbound.get(tenant_id, 0),
            outbound=sent_row["sent_total"] if sent_row else 0,
            users=sent_row["users"] if sent_row else 0,
            billable=sent_row["billable_total"] if sent_row else 0,
            pricing_counts=pricing.get(tenant_id, {}),
        )
    return result
