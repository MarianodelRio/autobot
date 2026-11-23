# ruff: noqa: F811
"""Ambiguous sends are reconciled (ADR-026): resent once after the wait when a duplicate is
harmless, never twice, never expired, never on evidence of delivery."""

from datetime import timedelta
from typing import Any

import httpx
import pytest
from django.utils import timezone

from autobot.channels import adapters
from autobot.channels.base import StatusItem
from autobot.runtime import outbound, process, reconcile
from autobot.runtime.models import Notification, OutboundMessage
from autobot.runtime.outbound import RECONCILE_WAIT, dup_policy
from autobot.tenancy.tx import tenant_tx
from tests.helpers.integration import jobs, wa_tenant
from tests.platform.runtime.test_outbound_expiry import (  # noqa: F401
    Clock,
    Meta,
    clock,
    meta,
    reload,
    reply_to,
    tenant,
    try_send,
)

pytestmark = [
    pytest.mark.django_db(transaction=True, databases=["default", "owner"]),
    pytest.mark.usefixtures("clean_jobs"),
]


def make_unknown(message: OutboundMessage, clock: Clock, **fields: Any) -> OutboundMessage:
    OutboundMessage.objects.using("owner").filter(id=message.id).update(
        status="unknown", unknown_at=clock.now, last_error="timeout", **fields
    )
    return reload(message)


def run() -> reconcile.ReconcileResult:
    return reconcile.reconcile_tenant(tenant(), timezone.now())


def test_resent_once_after_the_wait_not_before(tenants: Any, clock: Clock, meta: Meta) -> None:
    tenants(wa_tenant())
    message = make_unknown(reply_to(), clock)
    jobs_before = len(jobs())
    clock.advance(minutes=9)
    assert run().resent == 0 and reload(message).status == "unknown"

    clock.advance(minutes=2)
    assert run().resent == 1
    resent = reload(message)
    assert resent.status == "pending" and resent.ambiguous_resends == 1
    assert resent.unknown_at is None
    assert len(jobs()) == jobs_before + 1
    name, lock, args, queue = jobs()[-1]
    assert (
        (name, queue) == ("send_message", "outbound")
        and lock is not None
        and lock.startswith("out:")
    )
    assert args == {"tenant_id": str(message.tenant_id), "outbound_id": str(message.id)}

    try_send(message)
    assert reload(message).status == "sent" and len(meta.sent_texts()) == 1


def test_never_twice(tenants: Any, clock: Clock, meta: Meta, monkeypatch: Any) -> None:
    tenants(wa_tenant())
    message = make_unknown(reply_to(), clock)
    clock.advance(minutes=11)
    assert run().resent == 1
    # The resend is ambiguous again (a 500 with no body): it stays unknown for a person.
    monkeypatch.setattr(
        adapters.WHATSAPP,
        "client",
        httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(500))),
    )
    try_send(message)
    again = reload(message)
    assert again.status == "unknown" and again.ambiguous_resends == 1
    clock.advance(hours=1)
    assert run().resent == 0
    assert reload(message).status == "unknown"


def test_a_status_webhook_is_evidence(tenants: Any, clock: Clock, meta: Meta) -> None:
    tenants(wa_tenant())
    message = make_unknown(reply_to(), clock)
    with tenant_tx(tenant().id):
        process._update_from_status(
            OutboundMessage.objects.get(id=message.id),
            StatusItem(
                provider_event_id="e1",
                outbound_ref=None,
                provider_message_id="wamid.1",
                status="delivered",
                pricing_category=None,
                billable=None,
                error=None,
                payload={},
            ),
        )
    clock.advance(minutes=11)
    assert run().resent == 0
    assert reload(message).status == "sent" and not meta.requests


def test_a_provider_id_is_evidence(tenants: Any, clock: Clock, meta: Meta) -> None:
    tenants(wa_tenant())
    message = make_unknown(reply_to(), clock, provider_message_id="wamid.9")
    clock.advance(minutes=11)
    assert run().resent == 0 and reload(message).status == "unknown"


def test_an_expired_message_is_marked_expired_not_resent(
    tenants: Any, clock: Clock, meta: Meta
) -> None:
    tenants(wa_tenant())
    message = make_unknown(reply_to(), clock)
    clock.advance(minutes=31)  # past the reply's 30 minutes
    result = run()
    assert (result.resent, result.expired) == (0, 1)
    assert reload(message).status == "expired" and not meta.requests


def test_an_unsafe_class_stays_for_a_person(
    tenants: Any, clock: Clock, meta: Meta, monkeypatch: Any
) -> None:
    tenants(wa_tenant())
    message = make_unknown(reply_to(), clock)
    monkeypatch.setattr(reconcile, "SAFE_DUP_KINDS", ())
    clock.advance(minutes=11)
    assert run().resent == 0 and reload(message).status == "unknown"
    assert dup_policy("reply") == dup_policy("proactive") == "safe"
    assert dup_policy("payment") == "unsafe"


def test_a_person_resend_is_not_doubled(tenants: Any, clock: Clock, meta: Meta) -> None:
    from autobot.ops import actions

    tenants(wa_tenant())
    message = make_unknown(reply_to(), clock)
    clock.advance(minutes=11)
    assert actions.resend(message.id, actor="op").ok
    assert reload(message).ambiguous_resends == 1
    OutboundMessage.objects.using("owner").filter(id=message.id).update(
        status="unknown", unknown_at=clock.now
    )
    clock.advance(minutes=11)
    assert run().resent == 0


def test_the_periodic_task_is_registered() -> None:
    from autobot.runtime.jobs import RECONCILE_UNKNOWN, app

    assert RECONCILE_UNKNOWN in app.tasks
    assert timedelta(minutes=10) == RECONCILE_WAIT
    assert outbound.MAX_AMBIGUOUS_RESENDS == 1


def test_held_notices_expire(tenants: Any, clock: Clock) -> None:
    tenants(wa_tenant())
    with tenant_tx(tenant().id):
        row = Notification.objects.create(
            tenant_id=tenant().id, idem_key="n", kind="booking", text="x", status="held"
        )
    assert reconcile.expire_held(tenant().id, clock.now) == 0
    clock.advance(hours=3)
    assert reconcile.expire_held(tenant().id, clock.now) == 1
    assert Notification.objects.using("owner").get(id=row.id).status == "expired"
