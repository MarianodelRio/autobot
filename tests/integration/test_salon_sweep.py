"""Actual outbox deduplication for the real calendar sweep."""

import time
from datetime import timedelta
from typing import Any

import pytest

from flowpilot.runtime import periodic
from flowpilot.runtime.models import Channel, Contact, OutboundMessage
from flowpilot.tenancy.tx import tenant_tx
from packs.salon.models import CalendarEvent

pytestmark = [
    pytest.mark.django_db(transaction=True, databases=["default", "owner"]),
    pytest.mark.usefixtures("clean_jobs"),
]


def test_reminder_sent_once_per_contact(salon_setup: Any) -> None:
    from django.utils import timezone

    setup, calendars = salon_setup
    tenant = setup(config={"reminders_enabled": True})
    now = timezone.now()
    with tenant_tx(tenant.id):
        main = Contact.objects.create(
            tenant_id=tenant.id, channel=Channel.MAIN, external_id="34600000001"
        )
    calendars.main.add(
        CalendarEvent(
            "same-id",
            "Corte - Lucía",
            "",
            now + timedelta(hours=24),
            now + timedelta(hours=24, minutes=30),
            private={"fp_key": "key", "fp_contact": str(main.id)},
        )
    )
    periodic.run_periodic(tenant.id, "calendar_sweep", int(time.time()))
    periodic.run_periodic(tenant.id, "calendar_sweep", int(time.time()))
    (row,) = OutboundMessage.objects.using("owner").all()
    assert (row.channel, row.contact_id) == ("main", main.id)


def test_onboarding_never_confirms_manuals(salon_setup: Any) -> None:
    from django.utils import timezone

    setup, calendars = salon_setup
    setup(
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
    assert periodic.dispatch("salon", "calendar_sweep", int(time.time())) == 0
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
