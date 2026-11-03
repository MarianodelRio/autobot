"""Operator commands for resolving ambiguous sends and retrying failed jobs by hand,
when the panel is not reachable: `outbound_resolve` and `job_retry`."""

from datetime import timedelta
from io import StringIO
from typing import Any

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connections
from django.utils import timezone

from autobot.ops.actions import queue_app
from autobot.ops.models import AuditEvent
from autobot.runtime.models import Contact, OutboundMessage
from autobot.tenancy.models import Tenant
from core.replies import Text
from core.serialization import dump_outbound
from tests.integration.helpers import tg_tenant

pytestmark = pytest.mark.django_db(transaction=True, databases=["default", "owner"])


@pytest.fixture
def message(tenants: Any) -> OutboundMessage:
    doc = tg_tenant()
    tenants(doc)
    tenant = Tenant.objects.using("owner").get(pk=doc["id"])
    contact = Contact.objects.using("owner").create(
        tenant=tenant, channel="main", external_id="100000001"
    )
    return OutboundMessage.objects.using("owner").create(
        tenant=tenant,
        contact=contact,
        channel="main",
        kind="reply",
        idem_key="test:unknown",
        payload=dump_outbound(Text("hola")),
        status="unknown",
        unknown_at=timezone.now() - timedelta(minutes=11),
        attempts=1,
    )


def test_outbound_resolve_requires_confirm(message: OutboundMessage) -> None:
    with pytest.raises(CommandError, match="--confirm"):
        call_command("outbound_resolve", str(message.pk), "--mark-sent")
    message.refresh_from_db(using="owner")
    assert message.status == "unknown"


def test_outbound_resolve_mark_sent(message: OutboundMessage) -> None:
    output = StringIO()
    call_command("outbound_resolve", str(message.pk), "--mark-sent", "--confirm", stdout=output)
    message.refresh_from_db(using="owner")
    assert message.status == "sent"
    assert AuditEvent.objects.using("owner").filter(target_id=str(message.pk)).exists()


def test_outbound_resolve_rejects_ineligible(message: OutboundMessage) -> None:
    message.status = "sent"
    message.save(using="owner")
    with pytest.raises(CommandError):
        call_command("outbound_resolve", str(message.pk), "--mark-sent", "--confirm")


@pytest.mark.usefixtures("clean_jobs")
def test_job_retry_happy_path() -> None:
    pk = queue_app().configure_task("ops_check").defer()
    with connections["owner"].cursor() as cursor:
        cursor.execute("UPDATE procrastinate_jobs SET status='failed' WHERE id=%s", [pk])
    output = StringIO()
    call_command("job_retry", str(pk), stdout=output)
    assert AuditEvent.objects.using("owner").filter(target_id=str(pk)).exists()


@pytest.mark.usefixtures("clean_jobs")
def test_job_retry_rejects_delivery_jobs() -> None:
    pk = queue_app().configure_task("send_message").defer()
    with connections["owner"].cursor() as cursor:
        cursor.execute("UPDATE procrastinate_jobs SET status='failed' WHERE id=%s", [pk])
    with pytest.raises(CommandError):
        call_command("job_retry", str(pk))
