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


def test_migration_reuses_current_bsuid_and_preserves_opt_out(salon_setup: Any) -> None:
    import time

    from django.utils import timezone

    from flowpilot.runtime import periodic
    from flowpilot.runtime.models import OutboundMessage
    from flowpilot.tenancy.tx import tenant_tx

    setup, calendars = salon_setup
    tenant = setup(config={"reminders_enabled": True})
    with tenant_tx(tenant.id):
        current = Contact.objects.create(
            tenant_id=tenant.id,
            channel="main",
            external_id="ES.Current",
            phone_e164="+34600000001",
            opt_out=True,
        )
    now = timezone.now()
    calendars.main.add(
        CalendarEvent(
            "legacy",
            "Corte - Lucía",
            "WaId: 34600000001\nTelefono: +34600000001",
            now + timedelta(hours=24),
            now + timedelta(hours=24, minutes=30),
        )
    )
    assert main([tenant.slug], calendars=calendars, at=NOW) == 0
    assert calendars.main.events["legacy"].private["fp_contact"] == str(current.id)
    assert Contact.objects.using("owner").count() == 1
    periodic.run_periodic(tenant.id, "calendar_sweep", int(time.time()))
    assert not OutboundMessage.objects.using("owner").exists()


def test_migration_rejects_ambiguous_bsuid_and_does_not_create_contact(salon_setup: Any) -> None:
    from flowpilot.tenancy.tx import tenant_tx

    setup, calendars = salon_setup
    tenant = setup()
    with tenant_tx(tenant.id):
        for external in ("ES.First", "ES.Second"):
            Contact.objects.create(
                tenant_id=tenant.id, channel="main", external_id=external, phone_e164="+34600000001"
            )
    calendars.main.add(
        CalendarEvent(
            "legacy",
            "Corte - Lucía",
            "WaId: 34600000001\nTelefono: +34600000001",
            NOW + timedelta(days=1),
            NOW + timedelta(days=1, minutes=30),
        )
    )
    assert main([tenant.slug], calendars=calendars, at=NOW) == 1
    assert Contact.objects.using("owner").count() == 2
    assert calendars.main.events["legacy"].private == {}


def test_later_bsuid_can_manage_migrated_phone_identity(salon_setup: Any) -> None:
    from dataclasses import replace

    from core.testing.clock import FixedClock
    from flowpilot.runtime.context import build_context
    from flowpilot.runtime.models import Channel
    from flowpilot.runtime.process import _contact_info
    from flowpilot.tenancy.tx import tenant_tx
    from packs.salon.booking import contact_events

    setup, calendars = salon_setup
    tenant = setup()
    calendars.main.add(
        CalendarEvent(
            "legacy",
            "Corte - Lucía",
            "WaId: 34600000001",
            NOW + timedelta(days=1),
            NOW + timedelta(days=1, minutes=30),
        )
    )
    assert main([tenant.slug], calendars=calendars, at=NOW) == 0
    legacy = Contact.objects.using("owner").get()
    with tenant_tx(tenant.id):
        current = Contact.objects.create(
            tenant_id=tenant.id, channel="main", external_id="ES.Current", phone_e164="+34600000001"
        )
    info = _contact_info(current)
    assert info.alias_ids == (legacy.id,)
    ctx = build_context(
        tenant, Channel.MAIN, contact=info, state={}, event_id=None, calendars=calendars
    )
    ctx = replace(ctx, clock=FixedClock(NOW, tenant.info.timezone))
    assert [e.gcal_id for e in contact_events(ctx)] == ["legacy"]
    with tenant_tx(tenant.id):
        Contact.objects.create(
            tenant_id=tenant.id, channel="main", external_id="ES.Second", phone_e164="+34600000001"
        )
    assert _contact_info(current).alias_ids == ()


def test_migration_preserves_opt_out_on_numeric_identity_without_phone(salon_setup: Any) -> None:
    from flowpilot.tenancy.tx import tenant_tx

    setup, calendars = salon_setup
    tenant = setup()
    with tenant_tx(tenant.id):
        numeric = Contact.objects.create(
            tenant_id=tenant.id, channel="main", external_id="34600000001", opt_out=True
        )
        current = Contact.objects.create(
            tenant_id=tenant.id, channel="main", external_id="ES.Current", phone_e164="+34600000001"
        )
    calendars.main.add(
        CalendarEvent(
            "legacy",
            "Corte - Lucía",
            "WaId: 34600000001",
            NOW + timedelta(days=1),
            NOW + timedelta(days=1, minutes=30),
        )
    )
    assert main([tenant.slug], calendars=calendars, at=NOW) == 0
    assert calendars.main.events["legacy"].private["fp_contact"] == str(current.id)
    assert Contact.objects.using("owner").get(id=current.id).opt_out
    assert Contact.objects.using("owner").get(id=numeric.id).opt_out


@pytest.mark.parametrize("existing_bsuid", [True, False])
def test_explicit_legacy_bsuid_is_never_replaced_by_phone_match(
    salon_setup: Any, existing_bsuid: bool
) -> None:
    from flowpilot.tenancy.tx import tenant_tx

    setup, calendars = salon_setup
    tenant = setup()
    with tenant_tx(tenant.id):
        previous = Contact.objects.create(
            tenant_id=tenant.id,
            channel="main",
            external_id="ES.Current" if existing_bsuid else "34600000001",
            phone_e164="+34600000001" if existing_bsuid else None,
            opt_out=True,
        )
    calendars.main.add(
        CalendarEvent(
            "legacy",
            "Corte - Lucía",
            "WaId: ES.LegacyOther\nTelefono: +34600000001",
            NOW + timedelta(days=1),
            NOW + timedelta(days=1, minutes=30),
        )
    )
    code = main([tenant.slug], calendars=calendars, at=NOW)
    if existing_bsuid:
        assert code == 1 and calendars.main.events["legacy"].private == {}
        assert Contact.objects.using("owner").count() == 1
    else:
        assert code == 0
        selected = Contact.objects.using("owner").get(external_id="ES.LegacyOther")
        assert selected.id != previous.id and selected.opt_out and selected.phone_e164 is None
        assert calendars.main.events["legacy"].private["fp_contact"] == str(selected.id)
