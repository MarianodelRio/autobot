"""Calendar retention boundaries, short batches, and safe operator erasure."""

import io
import json
import stat
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from pytest_django import Settings

from autobot.jobs import app, retention_cleanup
from autobot.runtime import privacy, retention
from autobot.runtime.models import (
    Contact,
    Conversation,
    DemoEvent,
    DemoSession,
    InboundEvent,
    Notification,
    OutboundMessage,
)
from autobot.tenancy.models import Tenant
from tests.integration.helpers import demo_tenant, wa_tenant
from tests.integration.test_models import contact, event, outbound, tenant

pytestmark = pytest.mark.django_db(transaction=True, databases=["default", "owner"])
NOW = datetime(2026, 10, 25, 12, tzinfo=UTC)


def loaded(tenants: Any) -> Tenant:
    tenants(wa_tenant("a"), wa_tenant("b", status="offboarded"))
    return Tenant.objects.using("owner").get(slug="a")


@pytest.mark.parametrize("days", [29, 30, 89, 90])
def test_inbound_boundaries(tenants: Any, settings: Settings, days: int) -> None:
    a = loaded(tenants)
    settings.RETENTION_CLEANUP_ENABLED = True
    row = event(a)
    InboundEvent.objects.using("owner").filter(id=row.id).update(
        received_at=NOW - timedelta(days=days),
        payload={"text": "private"},
        effect_state={"gcal": "private"},
    )
    retention.cleanup(now=NOW)
    if days >= 90:
        assert not InboundEvent.objects.using("owner").exists()
    else:
        row.refresh_from_db(using="owner")
        assert row.payload == (None if days >= 30 else {"text": "private"})
        assert row.effect_state == ({} if days >= 30 else {"gcal": "private"})
        assert row.provider_event_id == "wamid.1"


@pytest.mark.parametrize(
    "age", [timedelta(days=29), timedelta(days=30), timedelta(days=364), timedelta(days=365)]
)
def test_outbound_and_notification_boundaries(
    tenants: Any, settings: Settings, age: timedelta
) -> None:
    a = loaded(tenants)
    settings.RETENTION_CLEANUP_ENABLED = True
    message = outbound(a, contact(a), "one", status="unknown")
    notice = Notification.objects.using("owner").create(
        tenant=a, idem_key="n", kind="daily", text="private"
    )
    OutboundMessage.objects.using("owner").filter(pk=message.pk).update(created_at=NOW - age)
    Notification.objects.using("owner").filter(pk=notice.pk).update(created_at=NOW - age)
    retention.cleanup(now=NOW)
    assert Notification.objects.using("owner").exists() == (age.days < 365)
    if age.days >= 365:
        assert not OutboundMessage.objects.using("owner").exists()
    else:
        message.refresh_from_db(using="owner")
        assert message.payload == (None if age.days >= 30 else {})
        assert message.status == "unknown"


@pytest.mark.parametrize(
    "last_activity", [None, NOW - timedelta(days=365), NOW - timedelta(days=364)]
)
def test_inactive_contact_cascades(
    tenants: Any, settings: Settings, last_activity: datetime | None
) -> None:
    a = loaded(tenants)
    settings.RETENTION_CLEANUP_ENABLED = True
    c = contact(a)
    Contact.objects.using("owner").filter(pk=c.pk).update(
        created_at=NOW - timedelta(days=366), last_activity_at=last_activity
    )
    Conversation.objects.using("owner").create(tenant=a, contact=c, state={"private": True})
    outbound(a, c, "one")
    retention.cleanup(now=NOW)
    survives = last_activity is not None and last_activity > retention.year_before(NOW)
    assert Contact.objects.using("owner").exists() == survives
    assert OutboundMessage.objects.using("owner").exists() == survives
    assert Conversation.objects.using("owner").exists() == survives


def test_leap_year_uses_calendar_months() -> None:
    assert retention.year_before(datetime(2024, 2, 29, tzinfo=UTC)) == datetime(
        2023, 2, 28, tzinfo=UTC
    )
    assert retention.year_before(datetime(2025, 3, 1, tzinfo=UTC)) == datetime(
        2024, 3, 1, tzinfo=UTC
    )


def test_selector_and_expired_conversations(tenants: Any, settings: Settings) -> None:
    a = loaded(tenants)
    settings.RETENTION_CLEANUP_ENABLED = True
    for index, days in enumerate([6, 7]):
        DemoEvent.objects.create(
            channel="demo_tg",
            provider_event_id=str(index),
            payload={},
            received_at=NOW - timedelta(days=days),
        )
    for index, days in enumerate([29, 30]):
        DemoSession.objects.create(
            channel="demo_tg",
            external_id=str(index),
            tenant=a,
            selected_at=NOW - timedelta(days=days),
        )
    expired = Conversation.objects.using("owner").create(
        tenant=a,
        contact=contact(a),
        state={"private": True},
        last_inbound_at=NOW - timedelta(days=1),
    )
    recent = Conversation.objects.using("owner").create(
        tenant=a, contact=contact(a, "other"), state={"private": True}, last_inbound_at=NOW
    )
    retention.cleanup(now=NOW)
    assert list(DemoEvent.objects.values_list("provider_event_id", flat=True)) == ["0"]
    assert list(DemoSession.objects.values_list("external_id", flat=True)) == ["0"]
    expired.refresh_from_db(using="owner")
    recent.refresh_from_db(using="owner")
    assert expired.state == {} and recent.state == {"private": True}


def test_all_tenants_batches_and_idempotence(tenants: Any, settings: Settings) -> None:
    loaded(tenants)
    settings.RETENTION_CLEANUP_ENABLED = True
    for t in Tenant.objects.using("owner").all():
        InboundEvent.objects.using("owner").bulk_create(
            [
                InboundEvent(
                    tenant=t,
                    channel="main",
                    kind="message",
                    provider_event_id=str(i),
                    payload={},
                    status="done",
                    received_at=NOW - timedelta(days=91),
                )
                for i in range(1001)
            ]
        )
    counts = []
    original = retention.apply_batches

    def tracked(*args: Any, **kwargs: Any) -> int:
        count = original(*args, **kwargs)
        counts.append(count)
        return count

    with patch.object(retention, "apply_batches", side_effect=tracked):
        retention.cleanup(now=NOW)
        retention.cleanup(now=NOW)
    assert not InboundEvent.objects.using("owner").exists()
    assert max(counts) == 1000 and counts.count(1) == 2


def test_disabled_job_is_inert(tenants: Any, settings: Settings) -> None:
    a = loaded(tenants)
    settings.RETENTION_CLEANUP_ENABLED = False
    row = event(a)
    InboundEvent.objects.using("owner").filter(pk=row.pk).update(
        received_at=NOW - timedelta(days=500)
    )
    retention_cleanup(timestamp=0)
    assert InboundEvent.objects.using("owner").exists()
    periodic = app.periodic_registry.periodic_tasks
    assert any(
        p.task.name == "retention_cleanup" and p.cron == "0 3 * * *" for p in periodic.values()
    )


def test_export_private_and_contact_ambiguity(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    a = tenant("a")
    c = contact(a, "111")
    contact(a, "111", "demo_tg")
    target = tmp_path / "export.json"
    with pytest.raises(CommandError, match="ambiguo"):
        call_command("export_contact", "a", "111", output=str(target))
    call_command("export_contact", "a", "111", channel="main", output=str(target))
    data = json.loads(target.read_text())
    assert data["data"]["contact"][0]["id"] == str(c.id)
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    assert "111" not in capsys.readouterr().out
    with pytest.raises(CommandError, match="archivo privado"):
        call_command("export_tenant", "a", output=str(target))
    assert json.loads(target.read_text()) == data


def test_forget_only_matching_contact_and_events() -> None:
    a, b = tenant("a"), tenant("b")
    c = contact(a, "111", "demo_tg")
    other_channel = contact(a, "111")
    other_tenant = contact(b, "111", "demo_tg")
    incoming = event(a, "incoming", "demo_tg")
    InboundEvent.objects.using("owner").filter(pk=incoming.pk).update(
        payload={"message": {"from": {"id": 111}}}
    )
    linked = event(a, "linked", "demo_tg")
    outbound(a, c, "one", inbound_event=linked)
    unrelated = event(a, "other", "main")
    foreign = event(b, "foreign", "demo_tg")
    DemoSession.objects.create(channel="demo_tg", external_id="111", tenant=b, selected_at=NOW)
    with pytest.raises(CommandError, match="ambiguo"):
        call_command("forget_contact", "a", "111")
    call_command("forget_contact", "a", "111", channel="demo_tg")
    assert set(Contact.objects.using("owner").values_list("pk", flat=True)) == {
        other_channel.pk,
        other_tenant.pk,
    }
    assert set(InboundEvent.objects.using("owner").values_list("pk", flat=True)) == {
        unrelated.pk,
        foreign.pk,
    }
    # DemoSession is keyed by (channel, external_id) alone, not by tenant: forgetting
    # this person's identity removes their one demo session, whichever tenant it points to.
    assert not DemoSession.objects.exists()


def test_purge_requires_exact_confirmation_and_preserves_other_tenant(tmp_path: Path) -> None:
    a, b = tenant("a"), tenant("b")
    for t in [a, b]:
        c = contact(t)
        e = event(t)
        Conversation.objects.using("owner").create(tenant=t, contact=c)
        outbound(t, c, "one", inbound_event=e)
        Notification.objects.using("owner").create(
            tenant=t, idem_key="one", kind="daily", text="private"
        )
        DemoSession.objects.create(
            channel="demo_tg", external_id=str(1 if t == a else 2), tenant=t, selected_at=NOW
        )
    DemoEvent.objects.create(channel="demo_tg", provider_event_id="99", payload={}, received_at=NOW)
    target = tmp_path / "tenant.json"
    call_command("export_tenant", "a", output=str(target), stdout=io.StringIO())
    assert all(
        row["tenant_id"] == str(a.id)
        for rows in json.loads(target.read_text())["data"].values()
        for row in rows
    )
    for confirmation in ["b", "a "]:
        with patch("builtins.input", return_value=confirmation), pytest.raises(CommandError):
            call_command("purge_tenant", "a")
        assert Contact.objects.using("owner").count() == 2
    with patch("builtins.input", return_value="a"):
        call_command("purge_tenant", "a")
    for model in privacy.MODELS:
        assert not model.objects.using("owner").filter(tenant=a).exists()
        assert model.objects.using("owner").filter(tenant=b).count() == 1
    assert Tenant.objects.using("owner").count() == 2
    assert DemoEvent.objects.exists()


@pytest.mark.parametrize("reference", ["recipient_id", "provider", "opaque", "sender"])
def test_whatsapp_erasure_associates_messages_and_statuses(reference: str) -> None:
    a = tenant("a")
    c = contact(a, "ES.subject")
    OutboundMessage.objects.using("owner").create(
        tenant=a,
        contact=c,
        channel="main",
        idem_key="sent",
        kind="reply",
        payload={},
        provider_message_id="wamid.out",
    )
    message = OutboundMessage.objects.using("owner").get()
    if reference == "sender":
        value = {"messages": [{"from_user_id": c.external_id}]}
    else:
        status_payload: dict[str, Any] = {
            "recipient_id": {"recipient_id": c.external_id},
            "provider": {"id": "wamid.out"},
            "opaque": {"biz_opaque_callback_data": str(message.id)},
        }[reference]
        value = {"statuses": [status_payload]}
    row = event(a)
    InboundEvent.objects.using("owner").filter(pk=row.pk).update(
        payload={"entry": [{"changes": [{"value": value}]}]}
    )
    assert privacy.contact_events(c) == {row.id}
    assert len(privacy.export_data(a, c)["data"]["inbound_event"]) == 1
    privacy.forget(c)
    assert not InboundEvent.objects.using("owner").exists()


@pytest.mark.parametrize("operation", ["forget", "purge"])
def test_demo_event_originals_follow_tenant_linkage(operation: str) -> None:
    a, b = tenant("a"), tenant("b")
    c = contact(a, "111", "demo_tg")
    for t, provider_id in [(a, "select:1"), (a, "2"), (b, "3")]:
        e = event(t, provider_id, "demo_tg")
        InboundEvent.objects.using("owner").filter(pk=e.pk).update(
            payload={"message": {"from": {"id": 111}}}
        )
    for provider_event_id in ["1", "2", "3", "4"]:
        DemoEvent.objects.create(
            channel="demo_tg",
            provider_event_id=provider_event_id,
            payload={"message": {"from": {"id": 111}}},
            received_at=NOW,
        )
    assert {
        row["provider_event_id"] for row in privacy.export_data(a, c)["data"]["demo_event"]
    } == {"1", "2"}
    if operation == "forget":
        privacy.forget(c)
    else:
        privacy.purge(a)
    assert set(DemoEvent.objects.values_list("provider_event_id", flat=True)) == {"3", "4"}
    assert InboundEvent.objects.using("owner").filter(tenant=b).exists()


def test_selector_refreshes_session_activity(
    tenants: Any, monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    from autobot.channels.demo import selector
    from autobot.channels.demo.doors import door

    settings.DEMO_TELEGRAM_TOKEN = "999:TEST-TOKEN"
    settings.DEMO_TELEGRAM_WEBHOOK_SECRET = "t" * 32
    settings.DEMO_TELEGRAM_USERS = frozenset({111})
    door.cache_clear()
    tenants(demo_tenant("a"))
    a = Tenant.objects.using("owner").get(slug="a")
    session = DemoSession.objects.create(
        channel="demo_tg", external_id="111", tenant=a, selected_at=NOW - timedelta(days=40)
    )
    e = DemoEvent.objects.create(
        channel="demo_tg",
        provider_event_id="55",
        received_at=NOW,
        payload={
            "update_id": 55,
            "message": {
                "message_id": 1,
                "from": {"id": 111, "is_bot": False, "first_name": "Private"},
                "chat": {"id": 111, "type": "private"},
                "date": 1791194400,
                "text": "hola",
            },
        },
    )
    monkeypatch.setattr(selector, "store", lambda *args: None)
    selector.route_demo_event(e.id)
    session.refresh_from_db()
    assert session.selected_at > NOW - timedelta(days=1)
    door.cache_clear()


def test_export_rejects_symlinks(tmp_path: Path) -> None:
    existing = tmp_path / "existing"
    existing.write_text("keep")
    link = tmp_path / "link"
    link.symlink_to(existing)
    with pytest.raises(CommandError):
        privacy.write_private(str(link), {"private": True})
    assert existing.read_text() == "keep"
