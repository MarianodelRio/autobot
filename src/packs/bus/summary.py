"""The owner's summary line for `bus` (ADR-007)."""

from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal

from core.pack import PackContext, SummaryLine


def summarize(
    ctx: PackContext, start: datetime, end: datetime, recorded: Mapping[str, Decimal]
) -> list[SummaryLine]:
    return [SummaryLine("🚌", "Consultas de horario", recorded.get("schedule_query", Decimal(0)))]
