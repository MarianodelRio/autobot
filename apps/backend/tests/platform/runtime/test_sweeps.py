"""The stuck-work sweeps of ops_check: nothing is lost if a job vanished."""

from datetime import timedelta
from typing import Any

import pytest
from django.db import connections
from django.utils import timezone

from autobot.runtime import sweeps
from autobot.runtime.inbound import initial_status
from autobot.runtime.models import InboundEvent, OutboundMessage
from autobot.tenancy.models import Tenant
from autobot.tenancy.registry import get_registry
from tests.helpers.integration import jobs, post_wa, wa_tenant, wa_text
from tests.platform.test_models import contact, outbound

pytestmark = pytest.mark.django_db(transaction=True, databases=["default", "owner"])


@pytest.fixture(autouse=True)
def _clean_jobs() -> Any:
    yield
    with connections["owner"].cursor() as cursor:
        cursor.execute("DELETE FROM procrastinate_periodic_defers")
        cursor.execute("DELETE FROM procrastinate_jobs")


def make(tenants: Any, status: str, age_min: int) -> tuple[Any, OutboundMessage]:
    tenants(wa_tenant())
    t = Tenant.objects.using("owner").get(slug="wa")
    msg = outbound(t, contact(t), "reply:1:0")
    OutboundMessage.objects.using("owner").filter(id=msg.id).update(
        status=status, created_at=timezone.now() - timedelta(minutes=age_min)
    )
    return get_registry().by_slug["wa"], msg


def test_a_sending_message_with_no_job_becomes_unknown(tenants: Any) -> None:
    tenant, msg = make(tenants, "sending", 11)
    result = sweeps.sweep_tenant(tenant)
    assert result.outbound_unknown == 1
    msg.refresh_from_db(using="owner")
    assert msg.status == "unknown" and msg.unknown_at is not None
    assert [j for j in jobs() if j[0] == "send_message"] == []  # never resent


def test_a_pending_message_with_no_job_is_queued_again_once(tenants: Any) -> None:
    tenant, msg = make(tenants, "pending", 11)
    assert sweeps.sweep_tenant(tenant).outbound_requeued == 1
    assert len([j for j in jobs() if j[0] == "send_message"]) == 1
    # Now a live job exists: the next tick leaves it alone.
    assert sweeps.sweep_tenant(tenant).outbound_requeued == 0
    assert len([j for j in jobs() if j[0] == "send_message"]) == 1


def test_a_recent_pending_message_is_left_alone(tenants: Any) -> None:
    tenant, _ = make(tenants, "pending", 2)
    assert sweeps.sweep_tenant(tenant) == sweeps.SweepResult()


def test_a_very_old_pending_message_is_reported_not_requeued(tenants: Any) -> None:
    tenant, _ = make(tenants, "pending", 60 * 30)
    result = sweeps.sweep_tenant(tenant)
    assert (result.outbound_stuck, result.outbound_requeued) == (1, 0)


def test_a_pending_inbound_event_with_no_job_is_reported_and_requeued(tenants: Any) -> None:
    tenants(wa_tenant())
    assert post_wa(wa_text("hola")) == 200  # saves the event and queues its job
    stored = InboundEvent.objects.using("owner").get()
    InboundEvent.objects.using("owner").filter(id=stored.id).update(
        received_at=timezone.now() - timedelta(minutes=6)
    )
    with connections["owner"].cursor() as cursor:
        cursor.execute("DELETE FROM procrastinate_jobs")  # the job got lost
    result = sweeps.sweep_tenant(get_registry().by_slug["wa"])
    assert (result.inbound_stuck, result.inbound_requeued) == (1, 1)
    assert len([j for j in jobs() if j[0] == "process_event"]) == 1


def test_a_requeued_event_goes_to_the_queue_of_its_pack(
    tenants: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A tenant whose pack needs Calendar is requeued in `inbound_ext`, as at the webhook."""
    import dataclasses

    from tests.fixtures.toy_pack import pack as toy

    monkeypatch.setattr(
        "packs.registry.PACKS", {"toy": dataclasses.replace(toy.pack, needs_calendar=True)}
    )
    tenants(wa_tenant())
    assert post_wa(wa_text("hola")) == 200
    stored = InboundEvent.objects.using("owner").get()
    InboundEvent.objects.using("owner").filter(id=stored.id).update(
        received_at=timezone.now() - timedelta(minutes=6)
    )
    with connections["owner"].cursor() as cursor:
        cursor.execute("DELETE FROM procrastinate_jobs")
    sweeps.sweep_tenant(get_registry().by_slug["wa"])
    assert [j[3] for j in jobs() if j[0] == "process_event"] == ["inbound_ext"]


def test_a_paused_tenant_still_applies_delivery_statuses(tenants: Any) -> None:
    tenants(wa_tenant(status="paused"))
    tenant = get_registry().by_slug["wa"]
    from autobot.channels.base import InboundItem, StatusItem

    status_item = StatusItem.__new__(StatusItem)
    assert not isinstance(status_item, InboundItem)
    assert initial_status(tenant, status_item) == InboundEvent.Status.PENDING
