"""Data rights: identity extraction, export of notices, demo grants on forget, and the
suppression ledger that `privacy_reapply` replays after a restore (ADR-019)."""

import json
from io import StringIO
from pathlib import Path
from typing import Any

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils import timezone

from autobot.ops.models import PrivacySuppression
from autobot.runtime import privacy, suppressions
from autobot.runtime.models import (
    Contact,
    DemoAccessGrant,
    DemoSession,
    InboundEvent,
    Notification,
)
from autobot.tenancy.models import Tenant
from tests.helpers.integration import tg_tenant

pytestmark = pytest.mark.django_db(transaction=True, databases=["default", "owner"])

TELEGRAM_KEYS = (
    "message",
    "edited_message",
    "callback_query",
    "channel_post",
    "edited_channel_post",
    "my_chat_member",
    "chat_member",
    "inline_query",
    "chosen_inline_result",
    "pre_checkout_query",
    "shipping_query",
    "business_message",
)


@pytest.mark.parametrize("key", TELEGRAM_KEYS)
def test_senders_cover_every_telegram_update_member(key: str) -> None:
    assert privacy._senders({"update_id": 1, key: {"from": {"id": 77}}}) == {"77"}


def test_senders_telegram_other_shapes() -> None:
    assert privacy._senders({"message_reaction": {"user": {"id": 5}}}) == {"5"}
    private = {"message": {"chat": {"id": 8, "type": "private"}, "from": {"id": 8}}}
    assert privacy._senders(private) == {"8"}
    group = {"message": {"chat": {"id": -100, "type": "group"}, "from": {"id": 9}}}
    assert privacy._senders(group) == {"9"}
    callback = {
        "callback_query": {
            "from": {"id": 4},
            "message": {"from": {"id": 999}, "chat": {"id": 4, "type": "private"}},
        }
    }
    assert privacy._senders(callback) == {"4"}  # never the bot's own id
    card = {"message": {"contact": {"user_id": 6, "phone_number": "+34600"}}}
    assert privacy._senders(card) == {"6", "34600"}


def test_senders_whatsapp_and_malformed() -> None:
    body = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [{"from": "34600"}],
                            "contacts": [{"wa_id": "34601", "user_id": "ES.1"}],
                            "statuses": [{"recipient_id": "34602"}],
                        }
                    }
                ]
            }
        ]
    }
    assert privacy._senders(body) == {"34600", "34601", "ES.1", "34602"}
    junk_payloads: tuple[Any, ...] = (
        None,
        [],
        {"entry": "x"},
        {"entry": [None, {"changes": 3}]},
        {"message": 3},
    )
    for junk in junk_payloads:
        assert privacy._senders(junk) == set()


@pytest.fixture
def tenant(tenants: Any) -> Tenant:
    doc = tg_tenant()
    tenants(doc)
    return Tenant.objects.using("owner").get(pk=doc["id"])


def make_contact(tenant: Tenant, channel: str = "main", external_id: str = "111") -> Contact:
    return Contact.objects.using("owner").create(
        tenant=tenant, channel=channel, external_id=external_id, display_name="Ana"
    )


def event(tenant: Tenant, channel: str, payload: dict[str, Any], pid: str) -> InboundEvent:
    return InboundEvent.objects.using("owner").create(
        tenant=tenant,
        channel=channel,
        kind="message",
        provider_event_id=pid,
        payload=payload,
        status="done",
        received_at=timezone.now(),
    )


def test_export_includes_only_this_contacts_notifications(tenant: Tenant) -> None:
    mine, other = make_contact(tenant), make_contact(tenant, external_id="222")
    for contact, text in ((mine, "Ana pidió cita"), (other, "Otro pidió cita"), (None, "Resumen")):
        Notification.objects.using("owner").create(
            tenant=tenant, kind="booking", contact=contact, text=text, idem_key=text
        )
    data = privacy.export_data(tenant, mine)["data"]
    assert [row["text"] for row in data["notification"]] == ["Ana pidió cita"]
    assert len(privacy.export_data(tenant)["data"]["notification"]) == 3


@pytest.mark.parametrize("key", TELEGRAM_KEYS)
def test_forget_erases_events_of_every_update_type(tenant: Tenant, key: str) -> None:
    contact = make_contact(tenant)
    mine = event(tenant, "main", {key: {"from": {"id": "111"}}}, "1")
    other = event(tenant, "main", {key: {"from": {"id": "999"}}}, "2")
    privacy.forget(contact)
    assert not InboundEvent.objects.using("owner").filter(pk=mine.pk).exists()
    assert InboundEvent.objects.using("owner").filter(pk=other.pk).exists()


def test_forget_erases_demo_grants_and_sessions_of_the_identity(tenant: Tenant) -> None:
    contact = make_contact(tenant, "demo_tg", "555")
    grant = {"granted_at": timezone.now()}
    DemoAccessGrant.objects.using("owner").create(channel="demo_tg", external_id="555", **grant)
    DemoAccessGrant.objects.using("owner").create(channel="demo_tg", external_id="556", **grant)
    DemoAccessGrant.objects.using("owner").create(channel="demo_wa", external_id="555", **grant)
    DemoSession.objects.using("owner").create(
        channel="demo_tg", external_id="555", tenant=tenant, selected_at=timezone.now()
    )
    exported = privacy.export_data(tenant, contact)["data"]
    assert [row["external_id"] for row in exported["demo_access_grant"]] == ["555"]
    privacy.forget(contact)
    left = DemoAccessGrant.objects.using("owner").values_list("channel", "external_id")
    assert sorted(left) == [("demo_tg", "556"), ("demo_wa", "555")]
    assert not DemoSession.objects.using("owner").exists()


def test_forget_writes_a_ledger_row_without_pii(tenant: Tenant) -> None:
    contact = make_contact(tenant)
    privacy.forget(contact)
    row = PrivacySuppression.objects.using("owner").get()
    assert (row.kind, row.tenant_id, row.contact_id) == ("forget", tenant.id, contact.id)
    assert row.identity_hashes == [suppressions.identity_hash("main", "111")]
    assert "111" not in json.dumps(suppressions.as_dict(row))


def test_forget_rolls_back_the_ledger_with_the_erasure(
    tenant: Tenant, monkeypatch: pytest.MonkeyPatch
) -> None:
    contact = make_contact(tenant)

    def boom(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(privacy, "_erase", boom)
    with pytest.raises(RuntimeError):
        privacy.forget(contact)
    assert not PrivacySuppression.objects.using("owner").exists()
    assert Contact.objects.using("owner").filter(pk=contact.pk).exists()


def test_reapply_after_restore_erases_again(tenant: Tenant, tmp_path: Path) -> None:
    contact = make_contact(tenant, "demo_tg", "555")
    snapshot_event = event(tenant, "demo_tg", {"message": {"from": {"id": "555"}}}, "9")
    privacy.forget(contact)
    ledger = StringIO()
    call_command("privacy_ledger_export", stdout=ledger)
    path = tmp_path / "ledger.jsonl"
    path.write_text(ledger.getvalue())
    assert len(ledger.getvalue().splitlines()) == 1

    # "Restore" an older snapshot: the ledger table is gone, the data is back.
    PrivacySuppression.objects.using("owner").all().delete()
    Contact.objects.using("owner").create(
        id=contact.id, tenant=tenant, channel="demo_tg", external_id="555"
    )
    event(tenant, "main", {"message": {"from": {"id": "555"}}}, "10")  # other channel
    DemoAccessGrant.objects.using("owner").create(
        channel="demo_tg", external_id="555", granted_at=timezone.now()
    )
    event(tenant, "demo_tg", {"message": {"from": {"id": "555"}}}, "11")

    out = StringIO()
    call_command("privacy_reapply", "--ledger", str(path), stdout=out)
    assert not Contact.objects.using("owner").filter(pk=contact.pk).exists()
    assert not DemoAccessGrant.objects.using("owner").exists()
    assert not InboundEvent.objects.using("owner").filter(channel="demo_tg").exists()
    assert InboundEvent.objects.using("owner").filter(channel="main").exists()
    assert snapshot_event.pk
    assert PrivacySuppression.objects.using("owner").count() == 1  # table complete again
    # Idempotent.
    call_command("privacy_reapply", "--ledger", str(path), stdout=out)
    assert PrivacySuppression.objects.using("owner").count() == 1


def test_reapply_erases_by_hash_when_the_contact_row_is_missing(tenant: Tenant) -> None:
    privacy.forget(make_contact(tenant, "demo_tg", "777"))  # ledger row for 777
    DemoSession.objects.using("owner").create(
        channel="demo_tg", external_id="777", tenant=tenant, selected_at=timezone.now()
    )
    result = privacy.reapply(suppressions.export_rows())
    assert result["other_rows"] == 1
    assert not DemoSession.objects.using("owner").exists()


def test_reapply_purges_a_restored_tenant(tenant: Tenant) -> None:
    Tenant.objects.using("owner").filter(pk=tenant.pk).update(status="offboarded")
    tenant.refresh_from_db(using="owner")
    privacy.forget(make_contact(tenant))
    privacy.purge(tenant)
    assert PrivacySuppression.objects.using("owner").count() == 1  # forget rows subsumed
    entry = PrivacySuppression.objects.using("owner").get(kind="purge")
    assert (entry.tenant_id, entry.contact_id, entry.identity_hashes) == (tenant.id, None, [])
    assert privacy.reapply(suppressions.export_rows())["tenants"] == 0  # nothing back yet

    # A restore brings the tenant back, even as 'active'; the ledger erases it again.
    Tenant.objects.using("owner").create(
        id=tenant.id,
        slug=tenant.slug,
        name="x",
        pack=tenant.pack,
        status="active",
        timezone=tenant.timezone,
        synced_at=timezone.now(),
    )
    make_contact(tenant)
    assert privacy.reapply(suppressions.export_rows())["tenants"] == 1
    assert not Tenant.objects.using("owner").filter(pk=tenant.pk).exists()
    assert not Contact.objects.using("owner").exists()


def test_reapply_rejects_invalid_ledger_files(tmp_path: Path) -> None:
    bad = tmp_path / "bad.jsonl"
    bad.write_text('{"ledger": "privacy.v1", "id": 1}\n')
    noise = tmp_path / "noise.jsonl"
    noise.write_text('{"msg": "startup"}\nnot json\n')
    call_command("privacy_reapply", "--ledger", str(noise), stdout=StringIO())
    with pytest.raises(CommandError, match="no válida"):
        call_command("privacy_reapply", "--ledger", str(bad))
    with pytest.raises(CommandError, match="No se pudo leer"):
        call_command("privacy_reapply", "--ledger", str(tmp_path / "missing"))


def test_reapply_reads_the_ledger_from_stdin(
    tenant: Tenant, monkeypatch: pytest.MonkeyPatch
) -> None:
    import io

    contact = make_contact(tenant)
    privacy.forget(contact)
    ledger = StringIO()
    call_command("privacy_ledger_export", stdout=ledger)
    PrivacySuppression.objects.using("owner").all().delete()
    Contact.objects.using("owner").create(id=contact.id, tenant=tenant, external_id="111")
    monkeypatch.setattr("sys.stdin", io.StringIO(ledger.getvalue()))
    call_command("privacy_reapply", "--ledger", "-", stdout=StringIO())
    assert not Contact.objects.using("owner").exists()
