import json
import uuid
from pathlib import Path
from typing import Any

import pytest
from django.contrib.auth.models import User
from django.db import connections
from django.test import RequestFactory
from django.utils import timezone

from autobot.ops.models import AuditEvent, OpsAlert
from autobot.panel.routers.contacts import contact_detail, contacts
from autobot.panel.services.activity import activity_page, describe_inbound, describe_outbound
from autobot.runtime.models import Contact, InboundEvent, Notification, OutboundMessage
from autobot.tenancy.models import Tenant


@pytest.mark.django_db(databases=["default", "owner"])
def test_activity_pagination_filters_and_contact_audit() -> None:
    now = timezone.now()
    tenant = Tenant.objects.using("owner").create(
        id=uuid.uuid7(),
        slug="test",
        name="Test",
        pack="toy",
        status="active",
        timezone="UTC",
        synced_at=now,
    )
    other = Tenant.objects.using("owner").create(
        id=uuid.uuid7(),
        slug="other",
        name="Other",
        pack="toy",
        status="active",
        timezone="UTC",
        synced_at=now,
    )
    contact = Contact.objects.using("owner").create(
        tenant=tenant, channel="main", external_id="123", display_name="Ana"
    )
    inbound = InboundEvent.objects.using("owner").create(
        tenant=tenant,
        channel="main",
        kind="message",
        provider_event_id="1",
        payload={"message": {"text": "Hola"}},
        status="done",
        received_at=now,
    )
    outbound = OutboundMessage.objects.using("owner").create(
        tenant=tenant,
        contact=contact,
        channel="main",
        kind="reply",
        idem_key="1",
        inbound_event=inbound,
        payload={"body": "Hola Ana"},
        status="sent",
    )
    OutboundMessage.objects.using("owner").filter(pk=outbound.pk).update(created_at=now)
    notice = Notification.objects.using("owner").create(
        tenant=tenant, idem_key="1", kind="booking", text="reserva", status="sent"
    )
    Notification.objects.using("owner").filter(pk=notice.pk).update(created_at=now)
    OpsAlert.objects.using("owner").create(
        tenant_id=tenant.id, kind="test", severity="warning", text="aviso", first_seen_at=now
    )
    AuditEvent.objects.using("owner").create(
        tenant_id=tenant.id, actor="operador", action="test", summary="cambio", at=now
    )
    with connections["owner"].cursor() as db:
        for t in (tenant, other):
            db.execute(
                "INSERT INTO procrastinate_jobs(task_name, queue_name, status, args, attempts) "
                "VALUES ('send_message', 'outbound', 'failed', %s, 3) RETURNING id",
                [json.dumps({"tenant_id": str(t.id)})],
            )
            job_id = db.fetchone()[0]
            db.execute(
                "INSERT INTO procrastinate_events(job_id, type, at) VALUES (%s, 'failed', %s)",
                [job_id, now],
            )
    items = []
    cursor = ""
    while True:
        page = activity_page(tenant="test", cursor=cursor, limit=1)
        items.extend(page.items)
        if not page.next_cursor:
            break
        cursor = page.next_cursor
    assert [item.kind for item in items] == [
        "inbound",
        "outbound",
        "notification",
        "alert",
        "audit",
        "job",
    ]
    assert len({(item.kind, item.id) for item in items}) == 6
    assert len(activity_page(tenant="test", kinds="job", status="failed").items) == 1
    assert activity_page(tenant="test", kinds="job", status="sent").items == []
    request = RequestFactory().get("/")
    request.user = User(username="operador")
    assert contacts(request, "test", search="Ana").items[0].id == contact.id
    detail = contact_detail(request, contact.id)
    assert detail.exchanges[0].inbound == "Hola"
    assert (
        AuditEvent.objects.using("owner")
        .filter(action="contact.view", target_id=str(contact.id))
        .exists()
    )


def test_descriptions_from_fixtures() -> None:
    root = Path("tests/fixtures")

    def fixture(channel: str, name: str) -> Any:
        return json.loads((root / channel / name).read_text())

    assert (
        describe_inbound("main", fixture("telegram", "message.json"))
        == "Hola, ¿a qué hora sale el bus?"
    )
    assert describe_inbound("main", fixture("whatsapp", "text.json")) == "Hola, quiero una cita"
    assert describe_inbound("main", None) == "(contenido no disponible)"
    assert describe_outbound(None) == "(contenido no disponible)"
    assert (
        describe_outbound(
            {
                "body": "Elige",
                "buttons": [{"title": "Sí"}],
                "sections": [{"rows": [{"title": "Mañana"}]}],
            }
        )
        == "Elige · Sí · Mañana"
    )
