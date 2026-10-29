"""The owner's summary line for `bus` (`docs/mejoras/02-avisos-y-resumenes.md` §4.3)."""

from decimal import Decimal

from core.pack import SummaryLine
from packs.bus import summary


def test_line_comes_from_the_recorded_schedule_query_metric() -> None:
    lines = summary.summarize(None, None, None, {"schedule_query": Decimal(7)})  # type: ignore[arg-type]
    assert lines == [SummaryLine("🚌", "Consultas de horario", Decimal(7))]


def test_line_is_zero_when_the_metric_is_missing() -> None:
    lines = summary.summarize(None, None, None, {})  # type: ignore[arg-type]
    assert lines == [SummaryLine("🚌", "Consultas de horario", Decimal(0))]
