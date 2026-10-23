"""Ported slot and Calendar-engine cases, with explicit clock and configuration."""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

import pytest

from packs.salon.models import CalendarEvent
from packs.salon.slots import classify, compute_slots, generate_slots, overlaps, split_periods

NOW = datetime.fromisoformat("2026-03-24T09:00:00+01:00")
DAY = NOW.date()


@dataclass
class Service:
    duration_min: int = 30
    client_presence_min: int = 30


@dataclass
class Rules:
    slot_step_min: int = 30
    min_notice_min: int = 0


def event(
    title: str = "Busy", start: str = "10:00", end: str = "10:30", **kwargs: object
) -> CalendarEvent:
    # Extra fields are tested separately; every busy event is a timed interval.
    return CalendarEvent(
        "test",
        title,
        "",
        datetime.combine(DAY, time.fromisoformat(start), NOW.tzinfo),
        datetime.combine(DAY, time.fromisoformat(end), NOW.tzinfo),
    )


@pytest.mark.parametrize(
    ("start", "end", "presence", "expected"),
    [
        ("10:00", "10:30", 30, ["10:00"]),
        ("10:00", "10:20", 30, []),
        ("10:00", "11:00", 30, ["10:00", "10:30"]),
        ("17:00", "21:00", 180, ["17:00", "17:30", "18:00"]),
        ("10:00", "14:00", 180, ["10:00", "10:30", "11:00"]),
    ],
)
def test_generate_slots(start: str, end: str, presence: int, expected: list[str]) -> None:
    assert [s.strftime("%H:%M") for s in generate_slots(start, end, presence)] == expected


@pytest.mark.parametrize(
    ("start", "end", "expected"),
    [
        (-30, 0, False),
        (0, 30, True),
        (30, 60, False),
        (-30, 15, True),
        (15, 60, True),
        (-30, 1, False),
        (-30, 2, True),
    ],
)
def test_overlap_tolerance(start: int, end: int, expected: bool) -> None:
    assert (
        overlaps(
            NOW + timedelta(minutes=start),
            NOW + timedelta(minutes=end),
            NOW,
            NOW + timedelta(minutes=30),
        )
        is expected
    )


def test_presence_limits_closing_but_occupation_limits_collisions() -> None:
    slots = compute_slots(
        DAY,
        Service(60, 180),
        [("10:00", "14:00")],
        [event(start="12:00", end="13:00")],
        NOW,
        Rules(),
    )
    assert slots == [time(10), time(10, 30), time(11)]


@pytest.mark.parametrize("title", ["[CFG] CERRADO", "[CFG] VACACIONES"])
def test_hard_close_overrides_schedule(title: str) -> None:
    assert (
        compute_slots(
            DAY,
            Service(),
            [("10:00", "14:00")],
            [event(title), event("[CFG] HORARIO 12:00-14:00")],
            NOW,
            Rules(),
        )
        == []
    )


def test_special_schedule_overrides_base() -> None:
    assert compute_slots(
        DAY, Service(), [("10:00", "14:00")], [event("[CFG] HORARIO 12:00-13:00")], NOW, Rules()
    ) == [time(12), time(12, 30)]


def test_multiday_closure_respects_exclusive_end() -> None:
    closed = CalendarEvent(
        "holiday",
        "[CFG] VACACIONES",
        "",
        NOW - timedelta(days=1),
        datetime.combine(DAY, time(), NOW.tzinfo),
        all_day=True,
    )
    assert compute_slots(DAY, Service(), [("10:00", "10:30")], [closed], NOW, Rules()) == [time(10)]


def test_advance_notice_and_past_days() -> None:
    assert compute_slots(
        DAY, Service(), [("09:00", "10:30")], [], NOW, Rules(min_notice_min=45)
    ) == [time(10)]
    assert compute_slots(date(2026, 3, 23), Service(), [("10:00", "14:00")], [], NOW, Rules()) == []


def test_period_split_uses_break_or_1400() -> None:
    slots = [time(10), time(13), time(14), time(17)]
    assert split_periods(slots, [("10:00", "14:00"), ("16:00", "21:00")]) == (slots[:3], slots[3:])
    assert split_periods(slots, [("10:00", "21:00")]) == (slots[:2], slots[2:])


def test_event_classification() -> None:
    from dataclasses import replace

    base = event()
    assert classify(base) == "block"
    assert classify(event("[CFG] CERRADO")) == "config"
    assert classify(replace(base, description="Telefono: +34600000001")) == "manual"
    assert classify(replace(base, private={"fp_key": "booking"})) == "bot"
