"""Two independent DB sessions compete for a real calendar advisory lock."""

import threading
import time
import uuid
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import date, datetime
from datetime import time as day_time
from typing import Any

import pytest
from django.db import close_old_connections, connections

from core.pack import ContactInfo
from core.testing.clock import FixedClock
from flowpilot.runtime.context import build_context
from flowpilot.runtime.models import Channel
from packs.salon.booking import SlotTaken, reserve
from packs.salon.models import CalendarEvent
from packs.salon.testing import FakeCalendar

pytestmark = pytest.mark.django_db(transaction=True, databases=["default", "owner"])
NOW = datetime.fromisoformat("2026-03-24T09:00:00+01:00")


class SlowCalendar(FakeCalendar):
    def insert_event(self, event: Mapping[str, Any], gcal_id: str) -> CalendarEvent:
        # Force the window where a second writer would see the slot as free if the
        # PostgreSQL lock were missing. No mutex in the fake hides that race.
        time.sleep(0.05)
        return super().insert_event(event, gcal_id)


def test_two_contacts_only_one_booking_and_retry_is_idempotent(salon_setup: Any) -> None:
    setup, _ = salon_setup
    tenant = setup()
    calendar = SlowCalendar()
    ready = threading.Barrier(2, timeout=10)
    event_ids = [uuid.uuid7(), uuid.uuid7()]
    contact_ids = [uuid.uuid7(), uuid.uuid7()]

    def attempt(index: int) -> tuple[str, str]:
        close_old_connections()
        try:
            contact = ContactInfo(contact_ids[index], str(index), None, "Lucía", False)
            ctx = build_context(
                tenant,
                Channel.MAIN,
                contact=contact,
                state={},
                event_id=event_ids[index],
                calendars=lambda _: calendar,
            )
            ctx = replace(ctx, clock=FixedClock(NOW, tenant.info.timezone))
            ready.wait()
            try:
                event = reserve(ctx, date(2026, 3, 24), day_time(10), "corte", "Lucía")
                return "created", event.gcal_id
            except SlotTaken:
                return "taken", ""
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(attempt, [0, 1]))
    assert sorted(status for status, _ in results) == ["created", "taken"]
    assert len(calendar.created) == 1
    winner = next(index for index, result in enumerate(results) if result[0] == "created")
    contact = ContactInfo(contact_ids[winner], str(winner), None, "Lucía", False)
    ctx = build_context(
        tenant,
        Channel.MAIN,
        contact=contact,
        state={},
        event_id=event_ids[winner],
        calendars=lambda _: calendar,
    )
    ctx = replace(ctx, clock=FixedClock(NOW, tenant.info.timezone))
    replay = reserve(ctx, date(2026, 3, 24), day_time(10), "corte", "Lucía")
    assert replay.gcal_id == calendar.created[0].gcal_id and len(calendar.created) == 1
    assert not connections["default"].in_atomic_block


def test_main_and_test_calendar_book_independently(salon_setup: Any) -> None:
    setup, calendars = salon_setup
    tenant = setup()
    contact = ContactInfo(uuid.uuid7(), "111", None, "Lucía", False)
    for channel in (Channel.MAIN, Channel.TEST):
        ctx = build_context(
            tenant, channel, contact=contact, state={}, event_id=uuid.uuid7(), calendars=calendars
        )
        ctx = replace(ctx, clock=FixedClock(NOW, tenant.info.timezone))
        reserve(ctx, date(2026, 3, 24), day_time(10), "corte", "Lucía")
    assert len(calendars.main.created) == len(calendars.test.created) == 1
