"""The owner's summary line for `salon`, over a `FakeCalendar`
(ADR-007)."""

import logging
from datetime import UTC, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from core.idem import IdemKeys
from core.pack import PackContext, SummaryLine
from core.testing.clock import FixedClock
from core.testing.harness import sample_tenant
from packs.salon import summary
from packs.salon.models import CalendarEvent
from packs.salon.testing import FakeCalendar
from packs.salon.tests.test_config import configuration

MADRID = ZoneInfo("Europe/Madrid")
START = datetime(2026, 10, 1, tzinfo=MADRID)
END = datetime(2026, 11, 1, tzinfo=MADRID)


def ctx(calendar: FakeCalendar, **config_changes: object) -> PackContext:
    tenant = sample_tenant()
    return PackContext(
        tenant=tenant,
        config=configuration(**config_changes),
        data=None,
        contact=None,
        state={},
        clock=FixedClock(datetime(2026, 11, 1, 9, tzinfo=UTC), tenant.timezone),
        calendar=calendar,
        lock=lambda key: None,  # type: ignore[arg-type,return-value]
        idem=IdemKeys(None),
        log=logging.getLogger("packs.salon"),
    )


def bot_event(
    gcal_id: str,
    summary_text: str,
    start: datetime,
    *,
    service: str,
    all_day: bool = False,
) -> CalendarEvent:
    return CalendarEvent(
        gcal_id,
        summary_text,
        "Nombre: Cliente",
        start,
        start,
        all_day=all_day,
        private={"fp_contact": "c", "fp_key": f"k:{gcal_id}", "fp_service": service},
    )


def manual_event(
    gcal_id: str, title: str, start: datetime, *, description: str = "", all_day: bool = False
) -> CalendarEvent:
    return CalendarEvent(gcal_id, title, description, start, start, all_day=all_day)


def test_counts_bot_events_and_manual_events_matching_a_service_title() -> None:
    cal = FakeCalendar()
    when = datetime(2026, 10, 10, 10, tzinfo=MADRID)
    cal.add(bot_event("e1", "Corte de pelo - Ana", when, service="corte"))
    cal.add(manual_event("e2", "corte de pelo", when))  # exact, folded
    cal.add(manual_event("e3", "TINTE – Bea", when))  # uppercase, en dash
    cal.add(manual_event("e4", "Tinte — Cruz", when))  # em dash
    lines = summary.summarize(ctx(cal), START, END, {})
    assert lines[0] == SummaryLine("✂️", "Citas", Decimal(4))
    assert lines[1].value == Decimal(10 + 10 + 50 + 50)
    assert lines[1].note is None


def test_ignores_config_vacation_meals_and_unmatched_manual_titles() -> None:
    cal = FakeCalendar()
    when = datetime(2026, 10, 10, 10, tzinfo=MADRID)
    cal.add(manual_event("e1", "[CFG] VACACIONES", when))
    cal.add(manual_event("e2", "Comida", when))
    cal.add(manual_event("e3", "Recado del dueño", when, description="Telefono: 600000001"))
    lines = summary.summarize(ctx(cal), START, END, {})
    assert lines[0].value == Decimal(0)


def test_ignores_all_day_events_and_events_outside_the_window() -> None:
    cal = FakeCalendar()
    cal.add(manual_event("e1", "Corte de pelo - Ana", datetime(2026, 10, 10, tzinfo=MADRID)))
    cal.add(
        manual_event("e2", "Tinte - Bea", datetime(2026, 10, 10, 10, tzinfo=MADRID), all_day=True)
    )
    cal.add(manual_event("e3", "Tinte - Cruz", datetime(2026, 9, 30, 23, tzinfo=MADRID)))
    lines = summary.summarize(ctx(cal), START, END, {})
    assert lines[0].value == Decimal(1)
    assert lines[1].value == Decimal(10)


def test_end_is_exclusive() -> None:
    cal = FakeCalendar()
    cal.add(manual_event("e1", "Corte de pelo - Ana", datetime(2026, 11, 1, tzinfo=MADRID)))
    lines = summary.summarize(ctx(cal), START, END, {})
    assert lines[0].value == Decimal(0)


def test_longest_service_name_wins() -> None:
    cal = FakeCalendar()
    when = datetime(2026, 10, 10, tzinfo=MADRID)
    cal.add(manual_event("e1", "Corte de pelo + barba - Ana", when))
    lines = summary.summarize(ctx(cal), START, END, {})
    assert lines[0].value == Decimal(1)
    assert lines[1].value == Decimal(12)  # corte_barba's price, not corte's


def test_bot_event_is_always_an_appointment_even_with_a_retired_service() -> None:
    cal = FakeCalendar()
    when = datetime(2026, 10, 10, tzinfo=MADRID)
    cal.add(bot_event("e1", "Corte de pelo - Ana", when, service="retired"))
    lines = summary.summarize(ctx(cal), START, END, {})
    assert lines[0].value == Decimal(1)
    assert lines[1].value == Decimal(10)  # recovered by title
    assert lines[1].note is None


def test_bot_event_with_a_retired_service_and_no_title_match_counts_unpriced() -> None:
    cal = FakeCalendar()
    when = datetime(2026, 10, 10, tzinfo=MADRID)
    cal.add(bot_event("e1", "Otro título cualquiera - Ana", when, service="retired"))
    lines = summary.summarize(ctx(cal), START, END, {})
    assert lines[0].value == Decimal(1)
    assert lines[1].value == Decimal(0)
    assert lines[1].note == "1 sin precio"


def test_revenue_sums_and_counts_the_unpriced() -> None:
    cal = FakeCalendar()
    when = datetime(2026, 10, 10, tzinfo=MADRID)
    cal.add(manual_event("e1", "Corte de pelo - Ana", when))  # priced: 10
    cal.add(bot_event("e2", "Sin coincidencia - Bea", when, service="retired"))  # unpriced
    lines = summary.summarize(ctx(cal), START, END, {})
    assert lines[0].value == Decimal(2)
    assert lines[1].value == Decimal(10)
    assert lines[1].note == "1 sin precio"
