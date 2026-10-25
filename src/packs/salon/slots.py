"""Pure slot engine ported from Peluqueria/utils/slots and calendar/engine."""

from collections.abc import Sequence
from datetime import date, datetime, time, timedelta
from typing import Protocol

from packs.salon.parser import parse_cfg
from packs.salon.ports import CalEvent


class ServiceRules(Protocol):
    @property
    def duration_min(self) -> int: ...
    @property
    def client_presence_min(self) -> int: ...


class SlotRules(Protocol):
    @property
    def slot_step_min(self) -> int: ...
    @property
    def min_notice_min(self) -> int: ...


def read_time(value: str) -> time:
    hour, minute = value.split(":")
    return time(int(hour), int(minute))


def generate_slots(start: str, end: str, presence_min: int = 30, step_min: int = 30) -> list[time]:
    if min(presence_min, step_min) <= 0:
        raise ValueError("slot lengths must be positive")
    begin, finish = read_time(start), read_time(end)
    minute = begin.hour * 60 + begin.minute
    last = finish.hour * 60 + finish.minute
    slots: list[time] = []
    while minute + presence_min <= last:
        slots.append(time(minute // 60, minute % 60))
        minute += step_min
    return slots


def overlaps(start: datetime, end: datetime, slot_start: datetime, slot_end: datetime) -> bool:
    tolerance = timedelta(minutes=1)
    return start + tolerance < slot_end and end - tolerance > slot_start


def classify(event: CalEvent) -> str:
    from packs.salon.parser import parse_phone

    if parse_cfg(event.summary):
        return "config"
    if event.private.get("fp_key"):
        return "bot"
    return "manual" if parse_phone(event.description) else "block"


def compute_slots(
    day: date,
    service: ServiceRules,
    spans: Sequence[tuple[str, str]],
    busy: Sequence[CalEvent],
    now: datetime,
    rules: SlotRules,
) -> list[time]:
    if now.tzinfo is None:
        raise ValueError("now must be aware")
    begin = datetime.combine(day, time(), now.tzinfo)
    end = datetime.combine(day + timedelta(days=1), time(), now.tzinfo)
    events = [e for e in busy if e.status != "cancelled" and e.start < end and e.end > begin]
    special: list[tuple[str, str]] | None = None
    blocking: list[CalEvent] = []
    for event in events:
        cfg = parse_cfg(event.summary)
        if cfg and cfg["type"] in ("cerrado", "vacaciones"):
            return []
        if cfg and cfg["type"] == "horario":
            if special is None:
                special = [(cfg["start"], cfg["end"])]
        else:
            blocking.append(event)
    ranges = special if special is not None else spans
    result: list[time] = []
    for start, stop in ranges:
        for slot in generate_slots(start, stop, service.client_presence_min, rules.slot_step_min):
            at = datetime.combine(day, slot, now.tzinfo)
            if at < now + timedelta(minutes=rules.min_notice_min):
                continue
            finish = at + timedelta(minutes=service.duration_min)
            if not any(overlaps(e.start, e.end, at, finish) for e in blocking):
                result.append(slot)
    return sorted(set(result))


def split_periods(
    slots: Sequence[time], spans: Sequence[tuple[str, str]]
) -> tuple[list[time], list[time]]:
    ranges = sorted(spans)
    boundary = read_time(ranges[1][0]) if len(ranges) > 1 else time(14)
    return [s for s in slots if s < boundary], [s for s in slots if s >= boundary]
