"""Availability and idempotent booking under the runtime's calendar lock."""

import base64
import hashlib
from collections.abc import Sequence
from datetime import date, datetime, time, timedelta
from typing import cast

from core.errors import PermanentError
from core.pack import PackContext
from packs.salon.config import SalonConfig
from packs.salon.ownership import belongs
from packs.salon.parser import parse_cfg
from packs.salon.ports import CalendarPort, CalEvent
from packs.salon.slots import compute_slots


class SlotTaken(Exception):
    pass


def calendar(ctx: PackContext) -> CalendarPort:
    return cast(CalendarPort, ctx.calendar)


def configuration(ctx: PackContext) -> SalonConfig:
    assert isinstance(ctx.config, SalonConfig)
    return ctx.config


def availability(
    ctx: PackContext,
    day: date,
    service_key: str,
    *,
    event: bool = False,
    busy: Sequence[CalEvent] | None = None,
) -> tuple[list[time], list[tuple[str, str]]]:
    cfg = configuration(ctx)
    now = ctx.clock.now()
    start = datetime.combine(day, time(), now.tzinfo)
    end = datetime.combine(day + timedelta(days=1), time(), now.tzinfo)
    events = calendar(ctx).list_events(start, end) if busy is None else busy
    ranges = cfg.spans(day, event=event)
    slots = compute_slots(day, cfg.services[service_key], ranges, events, now, cfg)
    for item in events:
        if item.status == "cancelled" or item.start >= end or item.end <= start:
            continue
        schedule = parse_cfg(item.summary)
        if schedule and schedule["type"] == "horario":
            ranges = [(schedule["start"], schedule["end"])]
            break
    return slots, ranges


def day_slots(
    ctx: PackContext,
    day: date,
    service_key: str,
    *,
    event: bool = False,
    busy: Sequence[CalEvent] | None = None,
) -> list[time]:
    return availability(ctx, day, service_key, event=event, busy=busy)[0]


def available_days(ctx: PackContext, service_key: str, *, event: bool = False) -> list[date]:
    cfg, now = configuration(ctx), ctx.clock.now()
    days = (
        sorted(d for d in cfg.special_event.days if d >= now.date())
        if event
        else [now.date() + timedelta(days=n) for n in range(cfg.booking_window_days + 1)]
    )
    if not days:
        return []
    start = datetime.combine(days[0], time(), now.tzinfo)
    end = datetime.combine(days[-1] + timedelta(days=1), time(), now.tzinfo)
    busy = calendar(ctx).list_events(start, end)
    return [d for d in days if day_slots(ctx, d, service_key, event=event, busy=busy)]


def contact_events(ctx: PackContext) -> Sequence[CalEvent]:
    assert ctx.contact is not None
    cfg, now = configuration(ctx), ctx.clock.now()
    end = now + timedelta(days=cfg.booking_window_days + 1)
    if cfg.special_event.active and cfg.special_event.days:
        end = max(
            end,
            datetime.combine(max(cfg.special_event.days) + timedelta(days=1), time(), now.tzinfo),
        )
    return [
        e
        for e in calendar(ctx).list_contact_events(
            str(ctx.contact.id),
            ctx.contact.phone,
            now,
            end,
            external_id=ctx.contact.external_id,
            alias_ids=[str(key) for key in ctx.contact.alias_ids],
        )
        if e.start >= now
    ]


def reserve(
    ctx: PackContext,
    day: date,
    slot: time,
    service_key: str,
    name: str,
    *,
    event: bool = False,
    operation: str = "booking",
) -> CalEvent:
    assert ctx.contact is not None
    cfg = configuration(ctx)
    svc = cfg.services[service_key]
    key = ctx.idem.event(operation)
    gcal_id = event_id(ctx, operation)
    with ctx.lock(f"cal:{day.isoformat()}"):
        existing = calendar(ctx).get_event(gcal_id)
        if existing is not None:
            if existing.private.get("fp_key") != key or not belongs(
                existing, str(ctx.contact.id), None, None
            ):
                raise PermanentError("Calendar id collision")
            return existing
        if slot not in day_slots(ctx, day, service_key, event=event):
            raise SlotTaken()
        start = datetime.combine(day, slot, ctx.clock.now().tzinfo)
        end = start + timedelta(minutes=svc.duration_min)
        lines = [f"Nombre: {name}"]
        if ctx.contact.phone:
            lines.append(f"Telefono: {ctx.contact.phone}")
        lines += [f"Servicio: {service_key}", "Estado: confirmada"]
        raw = {
            "summary": f"{svc.name} - {name}",
            "description": "\n".join(lines),
            "start": {"dateTime": start.isoformat(), "timeZone": str(ctx.tenant.timezone)},
            "end": {"dateTime": end.isoformat(), "timeZone": str(ctx.tenant.timezone)},
            "extendedProperties": {
                "private": {
                    "fp_contact": str(ctx.contact.id),
                    "fp_key": key,
                    "fp_service": service_key,
                }
            },
        }
        result = calendar(ctx).insert_event(raw, gcal_id)
        if (
            result.gcal_id != gcal_id
            or result.start != start
            or result.end != end
            or result.private.get("fp_key") != key
        ):
            raise PermanentError("Calendar did not confirm booking")
        return result


def event_id(ctx: PackContext, operation: str = "booking") -> str:
    digest = hashlib.sha256(f"{ctx.tenant.id}:{ctx.idem.event(operation)}".encode()).digest()
    return base64.b32hexencode(digest).decode().lower()[:32]
