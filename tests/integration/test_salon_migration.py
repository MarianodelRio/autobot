"""Migration against real RLS-protected contacts and an isolated FakeCalendar."""

from datetime import datetime, timedelta
from typing import Any

import pytest

from flowpilot.runtime.models import Contact
from packs.salon.models import CalendarEvent
from tools.migrate_salon_events import main

pytestmark = pytest.mark.django_db(transaction=True, databases=["default", "owner"])
NOW = datetime.fromisoformat("2026-03-24T09:00:00+01:00")


def test_dry_run_writes_nothing_and_apply_is_idempotent(
    salon_setup: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    setup, calendars = salon_setup
    tenant = setup(status="onboarding")
    old = CalendarEvent(
        "legacy",
        "Corte y barba - Lucía",
        "WaId: ES.Legacy123\nTelefono: +34600000001\nEstado: confirmada",
        NOW + timedelta(days=100),
        NOW + timedelta(days=100, minutes=30),
        private={"custom": "preserve"},
    )
    calendars.main.add(old)
    assert main([tenant.slug, "--dry-run"], calendars=calendars, at=NOW) == 0
    assert not Contact.objects.using("owner").exists()
    assert calendars.main.events["legacy"] == old
    assert "patch_private" not in calendars.main.calls
    assert main([tenant.slug], calendars=calendars, at=NOW) == 0
    event = calendars.main.events["legacy"]
    (contact,) = Contact.objects.using("owner").all()
    assert contact.tenant_id == tenant.id and contact.channel == "main"
    assert event.private["fp_contact"] == str(contact.id)
    assert event.private["fp_service"] == "corte_barba"
    assert event.private["custom"] == "preserve"
    assert (
        event.description == old.description and event.start == old.start and event.end == old.end
    )
    assert main([tenant.slug], calendars=calendars, at=NOW) == 0
    assert Contact.objects.using("owner").count() == 1
    assert calendars.main.calls.count("patch_private") == 1
    assert calendars.test.calls == []
    output = capsys.readouterr().out
    assert "ES.Legacy123" not in output and "600000001" not in output


def test_unknown_services_and_other_owners_are_not_overwritten(salon_setup: Any) -> None:
    setup, calendars = salon_setup
    tenant = setup()
    for key, title, private in [
        ("unknown", "Unknown - Lucía", {}),
        ("foreign", "Corte - Lucía", {"fp_contact": "foreign"}),
    ]:
        calendars.main.add(
            CalendarEvent(
                key,
                title,
                "WaId: ES.Legacy123",
                NOW + timedelta(days=1),
                NOW + timedelta(days=1, minutes=30),
                private=private,
            )
        )
    assert main([tenant.slug], calendars=calendars, at=NOW) == 1
    assert "fp_key" not in calendars.main.events["unknown"].private
    assert calendars.main.events["foreign"].private == {"fp_contact": "foreign"}


def test_a_failed_patch_can_be_retried_without_duplicate_contacts(salon_setup: Any) -> None:
    from core.errors import TransientError

    setup, calendars = salon_setup
    tenant = setup()
    calendars.main.add(
        CalendarEvent(
            "legacy",
            "Corte - Lucía",
            "WaId: ES.Legacy123",
            NOW + timedelta(days=1),
            NOW + timedelta(days=1, minutes=30),
        )
    )
    calendars.main.fail("patch_private", TransientError("offline"))
    assert main([tenant.slug], calendars=calendars, at=NOW) == 1
    assert main([tenant.slug], calendars=calendars, at=NOW) == 0
    assert Contact.objects.using("owner").count() == 1
