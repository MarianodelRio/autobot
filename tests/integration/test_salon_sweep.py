"""Actual outbox deduplication and isolation between real and test calendars."""

import time
from datetime import timedelta
from typing import Any

import pytest
from pytest_django import Settings

from flowpilot.runtime import periodic
from flowpilot.runtime.models import Channel, Contact, OutboundMessage
from flowpilot.tenancy.tx import tenant_tx
from packs.salon.models import CalendarEvent

pytestmark = [
    pytest.mark.django_db(transaction=True, databases=["default", "owner"]),
    pytest.mark.usefixtures("clean_jobs"),
]


def test_reminders_once_per_calendar_and_contact(salon_setup: Any, settings: Settings) -> None:
    from django.utils import timezone

    settings.TEST_BOT_TOKEN = "999:TEST-TOKEN"
    setup, calendars = salon_setup
    tenant = setup(config={"reminders_enabled": True})
    now = timezone.now()
    with tenant_tx(tenant.id):
        main = Contact.objects.create(
            tenant_id=tenant.id, channel=Channel.MAIN, external_id="34600000001"
        )
        test = Contact.objects.create(tenant_id=tenant.id, channel=Channel.TEST, external_id="111")
    for cal, contact in [(calendars.main, main), (calendars.test, test)]:
        cal.add(
            CalendarEvent(
                "same-id",
                "Corte - Lucía",
                "",
                now + timedelta(hours=24),
                now + timedelta(hours=24, minutes=30),
                private={"fp_key": "key", "fp_contact": str(contact.id)},
            )
        )
    periodic.run_periodic(tenant.id, "calendar_sweep", int(time.time()))
    periodic.run_periodic(tenant.id, "calendar_sweep", int(time.time()))
    rows = list(OutboundMessage.objects.using("owner").all())
    assert len(rows) == 2 and {r.channel for r in rows} == {"main", "test"}
    assert len({r.idem_key for r in rows}) == 2
    assert {r.contact_id for r in rows} == {main.id, test.id}


def test_onboarding_only_sweeps_test_calendar_and_never_confirms_manuals(
    salon_setup: Any, settings: Settings
) -> None:
    from django.utils import timezone

    settings.TEST_BOT_TOKEN = "999:TEST-TOKEN"
    setup, calendars = salon_setup
    tenant = setup(
        status="onboarding",
        config={
            "manual_confirmations_enabled": True,
            "manual_confirmations_since": "2026-01-01T00:00:00+01:00",
        },
    )
    now = timezone.now()
    event = CalendarEvent(
        "manual",
        "Corte - Lucía",
        "Telefono: +34600000001",
        now + timedelta(days=1),
        now + timedelta(days=1, minutes=30),
        created=now,
    )
    calendars.main.add(event)
    calendars.test.add(event)
    assert periodic.dispatch("salon", "calendar_sweep", int(time.time())) == 1
    periodic.run_periodic(tenant.id, "calendar_sweep", int(time.time()))
    assert calendars.main.calls == []
    assert "patch_description" not in calendars.test.calls
    assert not OutboundMessage.objects.using("owner").exists()


def test_opted_out_contact_gets_no_reminder(salon_setup: Any) -> None:
    from django.utils import timezone

    setup, calendars = salon_setup
    tenant = setup(config={"reminders_enabled": True})
    with tenant_tx(tenant.id):
        contact = Contact.objects.create(
            tenant_id=tenant.id, channel=Channel.MAIN, external_id="34600000001", opt_out=True
        )
    now = timezone.now()
    calendars.main.add(
        CalendarEvent(
            "optout",
            "Corte - Lucía",
            "",
            now + timedelta(hours=24),
            now + timedelta(hours=24, minutes=30),
            private={"fp_key": "key", "fp_contact": str(contact.id)},
        )
    )
    periodic.run_periodic(tenant.id, "calendar_sweep", int(time.time()))
    assert not OutboundMessage.objects.using("owner").exists()


def test_main_failure_does_not_stop_the_test_sweep(salon_setup: Any, settings: Settings) -> None:
    from django.utils import timezone

    from core.errors import TransientError

    settings.TEST_BOT_TOKEN = "999:TEST-TOKEN"
    setup, calendars = salon_setup
    tenant = setup(config={"reminders_enabled": True})
    with tenant_tx(tenant.id):
        contact = Contact.objects.create(
            tenant_id=tenant.id, channel=Channel.TEST, external_id="111"
        )
    now = timezone.now()
    calendars.main.fail("list_events", TransientError("offline"))
    calendars.test.add(
        CalendarEvent(
            "test-only",
            "Corte - Lucía",
            "",
            now + timedelta(hours=24),
            now + timedelta(hours=24, minutes=30),
            private={"fp_key": "key", "fp_contact": str(contact.id)},
        )
    )
    with pytest.raises(TransientError):
        periodic.run_periodic(tenant.id, "calendar_sweep", int(time.time()))
    (row,) = OutboundMessage.objects.using("owner").all()
    assert row.channel == Channel.TEST and row.contact_id == contact.id


def test_revoked_test_contact_gets_no_reminder(salon_setup: Any, settings: Settings) -> None:
    from django.utils import timezone

    settings.TEST_BOT_TOKEN = "999:TEST-TOKEN"
    setup, calendars = salon_setup
    tenant = setup(status="onboarding", config={"reminders_enabled": True})
    with tenant_tx(tenant.id):
        contact = Contact.objects.create(
            tenant_id=tenant.id, channel=Channel.TEST, external_id="222"
        )
    now = timezone.now()
    calendars.test.add(
        CalendarEvent(
            "revoked",
            "Corte - Lucía",
            "",
            now + timedelta(hours=24),
            now + timedelta(hours=24, minutes=30),
            private={"fp_key": "key", "fp_contact": str(contact.id)},
        )
    )
    periodic.run_periodic(tenant.id, "calendar_sweep", int(time.time()))
    assert not OutboundMessage.objects.using("owner").exists()
