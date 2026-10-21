"""Schema of design.md §12.1 (T-2.2): unique constraints, composite foreign keys and RLS
enabled. The tests write through `owner` (it bypasses RLS) because they check the
constraints themselves; the isolation between tenants is tested in tests/isolation/."""

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from django.db import DatabaseError, IntegrityError, connections, transaction

from flowpilot.models import (
    Contact,
    Conversation,
    InboundEvent,
    Notification,
    OutboundMessage,
    Tenant,
    TestBotEvent,
)

pytestmark = pytest.mark.django_db(databases=["default", "owner"])
NOW = datetime(2026, 10, 5, 10, tzinfo=UTC)


def tenant(slug: str) -> Tenant:
    return Tenant.objects.using("owner").create(
        id=uuid.uuid7(),
        slug=slug,
        name=slug,
        pack="toy",
        status=Tenant.Status.ACTIVE,
        timezone="Europe/Madrid",
        synced_at=NOW,
    )


def contact(t: Tenant, external_id: str = "34600000001", channel: str = "main") -> Contact:
    return Contact.objects.using("owner").create(tenant=t, channel=channel, external_id=external_id)


def event(t: Tenant, provider_event_id: str = "wamid.1", channel: str = "main") -> InboundEvent:
    return InboundEvent.objects.using("owner").create(
        tenant=t,
        channel=channel,
        kind=InboundEvent.Kind.MESSAGE,
        provider_event_id=provider_event_id,
        payload={},
        status=InboundEvent.Status.PENDING,
        received_at=NOW,
    )


def outbound(t: Tenant, c: Contact, idem_key: str, **extra: Any) -> OutboundMessage:
    return OutboundMessage.objects.using("owner").create(
        tenant=t,
        contact=c,
        channel="main",
        idem_key=idem_key,
        kind=OutboundMessage.Kind.REPLY,
        payload={},
        **extra,
    )


def raises_integrity(fn: Any) -> None:
    with pytest.raises(IntegrityError), transaction.atomic(using="owner"):
        fn()


# ── Unique constraints ────────────────────────────────────────────────────


def test_duplicate_inbound_event_is_rejected() -> None:
    a = tenant("a")
    event(a, "wamid.1")
    raises_integrity(lambda: event(a, "wamid.1"))


def test_same_provider_event_in_another_channel_or_tenant_is_allowed() -> None:
    a, b = tenant("a"), tenant("b")
    event(a, "1")
    event(a, "1", channel="test")
    event(b, "1")


def test_duplicate_outbound_idem_key_is_rejected() -> None:
    a = tenant("a")
    c = contact(a)
    outbound(a, c, "reply:e1:0")
    raises_integrity(lambda: outbound(a, c, "reply:e1:0"))


def test_same_idem_key_in_another_tenant_is_allowed() -> None:
    a, b = tenant("a"), tenant("b")
    outbound(a, contact(a), "reminder:x")
    outbound(b, contact(b), "reminder:x")


def test_duplicate_notification_idem_key_is_rejected() -> None:
    a = tenant("a")

    def notify() -> Notification:
        return Notification.objects.using("owner").create(
            tenant=a, idem_key="notify:booking_created:e1", kind="booking_created", text="x"
        )

    notify()
    raises_integrity(notify)


def test_contact_is_unique_per_tenant_channel_and_external_id() -> None:
    a = tenant("a")
    contact(a, "34600000001")
    contact(a, "34600000001", channel="test")  # the same person on the test bot
    raises_integrity(lambda: contact(a, "34600000001"))


def test_one_conversation_per_contact() -> None:
    a = tenant("a")
    c = contact(a)
    Conversation.objects.using("owner").create(tenant=a, contact=c)
    raises_integrity(lambda: Conversation.objects.using("owner").create(tenant=a, contact=c))


def test_duplicate_test_bot_update_is_rejected() -> None:
    def save() -> TestBotEvent:
        return TestBotEvent.objects.using("owner").create(update_id=42, payload={}, received_at=NOW)

    save()
    raises_integrity(save)


# ── Composite foreign keys ────────────────────────────────────────────────


def test_child_cannot_point_to_a_parent_of_another_tenant() -> None:
    a, b = tenant("a"), tenant("b")
    ca = contact(a)
    raises_integrity(lambda: Conversation.objects.using("owner").create(tenant=b, contact=ca))
    raises_integrity(lambda: outbound(b, ca, "k"))
    ea = event(a)
    raises_integrity(lambda: outbound(b, contact(b), "k", inbound_event=ea))


def test_deleting_an_old_event_keeps_its_messages() -> None:
    a = tenant("a")
    e = event(a)
    message = outbound(a, contact(a), "reply:e:0", inbound_event=e)
    with connections["owner"].cursor() as cursor:  # in SQL, as retention may do
        cursor.execute("DELETE FROM inbound_event WHERE id = %s", [e.id])
    message.refresh_from_db(using="owner")
    assert message.inbound_event_id is None
    assert message.tenant_id == a.id


def test_deleting_a_contact_deletes_its_conversation_and_messages() -> None:
    a = tenant("a")
    c = contact(a)
    Conversation.objects.using("owner").create(tenant=a, contact=c)
    outbound(a, c, "k")
    with connections["owner"].cursor() as cursor:
        cursor.execute("DELETE FROM contact WHERE id = %s", [c.id])
    assert not Conversation.objects.using("owner").exists()
    assert not OutboundMessage.objects.using("owner").exists()


# ── Ids and RLS ───────────────────────────────────────────────────────────


def test_ids_are_uuidv7() -> None:
    assert contact(tenant("a")).id.version == 7


def test_rls_is_enabled_and_forced_on_tenant_tables_only() -> None:
    with connections["owner"].cursor() as cursor:
        cursor.execute(
            "SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class"
            " WHERE relname = ANY(%s)",
            [
                [
                    "tenant",
                    "contact",
                    "conversation",
                    "inbound_event",
                    "outbound_message",
                    "notification",
                    "test_bot_event",
                    "test_session",
                ]
            ],
        )
        flags = {name: (enabled, forced) for name, enabled, forced in cursor.fetchall()}
    platform = {"test_bot_event", "test_session"}
    assert {t for t, f in flags.items() if f == (True, True)} == set(flags) - platform
    assert all(flags[t] == (False, False) for t in platform)


@pytest.mark.parametrize(
    "sql",
    [
        "INSERT INTO tenant (id, slug, name, pack, status, timezone, synced_at)"
        " VALUES (gen_random_uuid(), 'x', 'x', 'toy', 'active', 'UTC', now())",
        "UPDATE tenant SET name = 'x'",
        "DELETE FROM tenant",
    ],
)
def test_fp_app_can_only_read_tenants(sql: str) -> None:
    with (
        pytest.raises(DatabaseError, match="permission denied"),
        transaction.atomic(using="default"),
        connections["default"].cursor() as cursor,
    ):
        cursor.execute(sql)


def test_defaults_exist_in_the_database() -> None:
    a = tenant("a")
    with connections["owner"].cursor() as cursor:
        cursor.execute(
            "INSERT INTO contact (id, tenant_id, channel, external_id, created_at)"
            " VALUES (%s, %s, 'main', 'x', now())"
            " RETURNING opt_out, unreachable, display_name",
            [uuid.uuid7(), a.id],
        )
        assert cursor.fetchone() == (False, False, "")


def test_no_redundant_tenant_index() -> None:
    with connections["owner"].cursor() as cursor:
        cursor.execute(
            "SELECT count(*) FROM pg_indexes WHERE tablename = 'contact'"
            " AND indexdef LIKE '%%(tenant_id)'"
        )
        assert cursor.fetchone() == (0,)
