"""Shared approximate messaging costs for owner summaries and the panel."""

import logging
from collections.abc import Mapping
from decimal import ROUND_HALF_UP, Decimal

from django.db.models import Count, QuerySet

from autobot.runtime.models import OutboundMessage

log = logging.getLogger(__name__)

# Approximate Meta price per delivered message, Spain, EUR. Not the account's real
# tariff (Meta's rate card is per recipient country and lives in each business's
# WhatsApp Manager billing panel). Last checked 2026-10-29; see
# docs/procedimientos/alta-baja-negocio.md.
PRICE_EUR: dict[str, Decimal] = {
    "marketing": Decimal("0.0585"),
    "utility": Decimal("0.0166"),
    "authentication": Decimal("0.0166"),
    "service": Decimal("0.0166"),
}


def billable_counts(queryset: QuerySet[OutboundMessage]) -> dict[str | None, int]:
    return dict(
        queryset.filter(billable=True)
        .order_by()
        .values("pricing_category")
        .annotate(total=Count("id"))
        .values_list("pricing_category", "total")
    )


def cost_of(counts: Mapping[str | None, int]) -> Decimal:
    highest = max(PRICE_EUR.values())
    cost = Decimal(0)
    for category, count in counts.items():
        price = PRICE_EUR.get(category) if category is not None else None
        if price is None:
            log.warning(
                "owner summary: unknown pricing category %r priced at the highest rate", category
            )
            price = highest
        cost += price * count
    return cost.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
