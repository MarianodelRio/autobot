"""Booking through the real webhook/runtime/outbox."""

import itertools
import json
import time
from datetime import datetime, timedelta
from typing import Any

import pytest

from core.clock import SystemClock
from flowpilot.runtime import periodic
from flowpilot.runtime.models import Contact, Notification, OutboundMessage
from packs.salon.models import CalendarEvent
from tests.integration.helpers import fixture, post_tg, post_wa, wa_press, wa_text
from tests.integration.test_test_bot import Providers, drain
from tests.integration.test_test_bot import providers as recorded_providers  # noqa: F401
from tests.integration.test_test_bot import test_bot as bot_settings  # noqa: F401

pytestmark = [
    pytest.mark.django_db(transaction=True, databases=["default", "owner"]),
    pytest.mark.usefixtures("clean_jobs"),
]
_ids = itertools.count(880000001)


@pytest.fixture(autouse=True)
def business_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    def now(self: SystemClock) -> datetime:
        return datetime(2026, 3, 24, 9, 0, tzinfo=self.tz)

    monkeypatch.setattr(SystemClock, "now", now)


def telegram(text: str, *, payload: bool = False) -> None:
    update = json.loads(
        fixture("telegram/callback_query.json" if payload else "telegram/message.json")
    )
    update["update_id"] = next(_ids)
    if payload:
        update["callback_query"]["id"] = str(next(_ids))
        update["callback_query"]["data"] = text
    else:
        update["message"]["text"] = text
    assert post_tg(json.dumps(update).encode()) == 200
    drain()


@pytest.mark.parametrize("channel", ["whatsapp", "telegram"])
def test_booking_over_every_channel(
    salon_setup: Any, request: pytest.FixtureRequest, channel: str
) -> None:
    providers: Providers = request.getfixturevalue("recorded_providers")
    setup, calendars = salon_setup
    slug = "wa" if channel == "whatsapp" else "tg"
    tenant = setup(
        channel=channel,
        slug=slug,
        config={"reminders_enabled": True, "reminder_window_hours": [0, 2]},
    )

    def send(text: str, *, payload: bool = False) -> None:
        if channel == "whatsapp":
            assert post_wa((wa_press if payload else wa_text)(text)) == 200
            drain()
        else:
            telegram(text, payload=payload)

    send("hola")
    for value in ["menu_book", "service_corte", "day_2026-03-24", "period_morning", "hour_10:00"]:
        send(value, payload=True)
    send("Lucía")
    assert len(calendars.main.created) == 1
    assert "confirmada" in str(
        list(OutboundMessage.objects.using("owner").values_list("payload", flat=True))
    )
    (contact,) = Contact.objects.using("owner").all()
    assert contact.channel == "main"
    assert calendars.main.created[0].private["fp_contact"] == str(contact.id)
    if channel == "telegram":
        assert providers.meta == []
        assert providers.telegram and all(
            not where.startswith("999:") for where, _ in providers.telegram
        )
    else:
        assert providers.meta and providers.telegram == []

    send("baja")
    periodic.run_periodic(tenant.id, "calendar_sweep", int(time.time()))
    assert Contact.objects.using("owner").get().opt_out
    assert not OutboundMessage.objects.using("owner").filter(kind="proactive").exists()


@pytest.mark.parametrize("channel", ["whatsapp", "telegram"])
def test_manual_confirmations_only_use_whatsapp(
    salon_setup: Any, channel: str, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level("INFO")
    setup, calendars = salon_setup
    tenant = setup(
        channel=channel,
        config={
            "manual_confirmations_enabled": True,
            "manual_confirmations_since": "2026-01-01T00:00:00+01:00",
        },
    )
    now = datetime.fromisoformat("2026-03-24T09:00:00+01:00")
    calendars.main.add(
        CalendarEvent(
            "manual",
            "Corte - Lucía",
            "Nombre: Lucía\nTelefono: +34600000001",
            now + timedelta(days=1),
            now + timedelta(days=1, minutes=30),
            created=now,
        )
    )
    periodic.run_periodic(tenant.id, "calendar_sweep", int(time.time()))
    periodic.run_periodic(tenant.id, "calendar_sweep", int(time.time()))
    messages = list(OutboundMessage.objects.using("owner").all())
    assert len(messages) == (1 if channel == "whatsapp" else 0)
    if channel == "telegram":
        assert "Manual confirmations skipped" in caplog.text
    if messages:
        assert messages[0].payload is not None
        assert messages[0].payload["template"]["name"] == "confirmacion_cita"
        assert Contact.objects.using("owner").get().channel == "main"


def test_delete_then_transient_failure_retries_with_owner_notice(
    salon_setup: Any, request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> None:
    from django.db import connections

    from core.errors import TransientError
    from flowpilot.runtime.models import InboundEvent

    request.getfixturevalue("recorded_providers")
    setup, calendars = salon_setup
    tenant = setup(
        slug="wa", owner={"telegram_chat_id": 987654321, "notify": ["booking_cancelled"]}
    )
    for value in [
        "hola",
        "menu_book",
        "service_corte",
        "day_2026-03-24",
        "period_morning",
        "hour_10:00",
        "Lucía",
        "back_to_menu",
        "menu_cancel",
    ]:
        assert post_wa((wa_text if value in ("hola", "Lucía") else wa_press)(value)) == 200
        drain()
    original = calendars.main.cancel_event

    def delete_then_fail(gcal_id: str) -> None:
        assert not connections["default"].in_atomic_block
        original(gcal_id)
        raise TransientError("verification temporarily unavailable")

    monkeypatch.setattr(calendars.main, "cancel_event", delete_then_fail)
    assert post_wa(wa_press("cancel_appt:0")) == 200
    with pytest.raises(TransientError):
        drain()
    event = InboundEvent.objects.using("owner").get(status="pending", tenant_id=tenant.id)
    assert event.effect_state
    monkeypatch.setattr(calendars.main, "cancel_event", original)
    drain()
    assert InboundEvent.objects.using("owner").get(id=event.id).status == "done"
    assert Notification.objects.using("owner").filter(kind="booking_cancelled").count() == 1
    assert len(calendars.main.cancelled) == 1
