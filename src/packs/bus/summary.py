"""The owner's summary line for `bus` (`docs/mejoras/02-avisos-y-resumenes.md` §4.3)."""

from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal

from core.pack import PackContext, SummaryLine


def summarize(
    ctx: PackContext, start: datetime, end: datetime, recorded: Mapping[str, Decimal]
) -> list[SummaryLine]:
    return [SummaryLine("🚌", "Consultas de horario", recorded.get("schedule_query", Decimal(0)))]
