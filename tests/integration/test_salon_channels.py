"""Booking through the real webhook/runtime/outbox, with both calendar instances."""

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
from tests.integration.test_test_bot import TESTER, Providers, drain, press, say
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


@pytest.mark.parametrize("mode", ["whatsapp", "telegram", "test-whatsapp", "test-telegram"])
def test_booking_over_every_channel(
    salon_setup: Any, request: pytest.FixtureRequest, mode: str
) -> None:
    providers: Providers = request.getfixturevalue("recorded_providers")
    setup, calendars = salon_setup
    is_test = mode.startswith("test-")
    channel = mode.removeprefix("test-")
    slug = "salon" if is_test else "wa" if channel == "whatsapp" else "tg"
    tenant = setup(
        channel=channel,
        slug=slug,
        status="onboarding" if is_test else "active",
        config={"reminders_enabled": True, "reminder_window_hours": [0, 2]},
    )
    if is_test:
        say(TESTER, "/start")
        drain()
        press(TESTER, f"fp_select:{tenant.slug}")
        drain()

    def send(text: str, *, payload: bool = False) -> None:
        if is_test:
            (press if payload else say)(TESTER, text)
            drain()
        elif channel == "whatsapp":
            assert post_wa((wa_press if payload else wa_text)(text)) == 200
            drain()
        else:
            telegram(text, payload=payload)

    if not is_test:
        send("hola")
    for value in ["menu_book", "service_corte", "day_2026-03-24", "period_morning", "hour_10:00"]:
        send(value, payload=True)
    send("Lucía")
    used, untouched = (
        (calendars.test, calendars.main) if is_test else (calendars.main, calendars.test)
    )
    assert len(used.created) == 1 and untouched.calls == []
    assert "confirmada" in str(
        list(OutboundMessage.objects.using("owner").values_list("payload", flat=True))
    )
    (contact,) = Contact.objects.using("owner").all()
    assert contact.channel == ("test" if is_test else "main")
    assert used.created[0].private["fp_contact"] == str(contact.id)
    if is_test:
        assert providers.meta == []
        (notice,) = Notification.objects.using("owner").all()
        assert notice.audience == "ops"
    elif channel == "telegram":
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
    assert calendars.test.calls == []  # Manual confirmations disabled: no test-calendar I/O.
    if channel == "telegram":
        assert "Manual confirmations skipped" in caplog.text
    if messages:
        assert messages[0].payload is not None
        assert messages[0].payload["template"]["name"] == "confirmacion_cita"
        assert Contact.objects.using("owner").get().channel == "main"
