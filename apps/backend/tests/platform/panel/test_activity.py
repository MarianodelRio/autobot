import json
import uuid
from pathlib import Path
from typing import Any

import pytest
from django.contrib.auth.models import User
from django.test import RequestFactory
from django.utils import timezone

from autobot.ops.models import AuditEvent
from autobot.panel.errors import ApiError
from autobot.panel.routers.contacts import contact_detail, contacts
from autobot.panel.services.activity import (
    activity_detail,
    activity_page,
    describe_inbound,
    describe_outbound,
)
from autobot.runtime.models import (
    Contact,
    Conversation,
    InboundEvent,
    Notification,
    OutboundMessage,
)
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
    Conversation.objects.using("owner").create(
        tenant=tenant, contact=contact, state={"step": "booking"}
    )
    other_contact = Contact.objects.using("owner").create(
        tenant=other, channel="main", external_id="999", display_name="Otro"
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
    OutboundMessage.objects.using("owner").create(
        tenant=other,
        contact=other_contact,
        channel="main",
        kind="reply",
        idem_key="1",
        payload={"body": "Hola Otro"},
        status="sent",
    )
    notice = Notification.objects.using("owner").create(
        tenant=tenant, idem_key="1", kind="booking", text="reserva", status="sent"
    )
    Notification.objects.using("owner").filter(pk=notice.pk).update(created_at=now)
    items = []
    cursor = ""
    while True:
        page = activity_page(tenant="test", cursor=cursor, limit=1)
        items.extend(page.items)
        if not page.next_cursor:
            break
        cursor = page.next_cursor
    assert [item.kind for item in items] == ["inbound", "outbound", "notification"]
    assert len({(item.kind, item.id) for item in items}) == 3
    # The feed carries no message text or contact name, only metadata.
    for item in items:
        assert "Hola" not in (item.label or "")
        assert "Ana" not in (item.label or "")

    request = RequestFactory().get("/")
    request.user = User(username="operador")
    assert contacts(request, "test", search="Ana").items[0].id == contact.id
    detail = contact_detail(request, contact.id)
    assert detail.exchanges[0].inbound == "Hola"
    assert detail.state == {"step": "booking"}
    assert (
        AuditEvent.objects.using("owner")
        .filter(action="contact.view", target_id=str(contact.id))
        .exists()
    )

    inbound_detail = activity_detail("inbound", str(inbound.pk), actor="operador")
    assert inbound_detail.text == "Hola"
    outbound_detail = activity_detail("outbound", str(outbound.pk), actor="operador")
    assert outbound_detail.contact == "Ana"
    assert outbound_detail.text == "Hola Ana"
    assert outbound_detail.contact_link == "/clientes/test?tab=contactos"
    notification_detail = activity_detail("notification", str(notice.pk), actor="operador")
    assert notification_detail.text == "reserva"

    event = (
        AuditEvent.objects.using("owner")
        .filter(action="activity.view", target_type="outbound", target_id=str(outbound.pk))
        .get()
    )
    assert "Hola Ana" not in json.dumps(event.details)
    assert "Ana" not in json.dumps(event.details)

    with pytest.raises(ApiError) as excinfo:
        activity_detail("alert", str(inbound.pk), actor="operador")
    assert excinfo.value.status == 404

    with pytest.raises(ApiError) as excinfo:
        activity_detail("inbound", "not-a-uuid", actor="operador")
    assert excinfo.value.status == 404


@pytest.mark.django_db(databases=["default", "owner"])
def test_the_errors_status_group_covers_failed_unknown_and_discarded() -> None:
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
    contact = Contact.objects.using("owner").create(
        tenant=tenant, channel="main", external_id="123", display_name="Ana"
    )
    for status in ("sent", "failed", "unknown", "discarded", "expired"):
        OutboundMessage.objects.using("owner").create(
            tenant=tenant,
            contact=contact,
            channel="main",
            kind="reply",
            idem_key=status,
            payload={"body": "x"},
            status=status,
        )
    InboundEvent.objects.using("owner").create(
        tenant=tenant,
        channel="main",
        kind="message",
        provider_event_id="1",
        payload={},
        status="failed",
        received_at=now,
    )

    page = activity_page(tenant="test", status="errors")
    assert sorted(str(item.status) for item in page.items) == ["discarded", "failed", "unknown"]
    assert {item.kind for item in page.items} == {"outbound"}
    exact = activity_page(tenant="test", kinds="outbound", status="expired")
    assert [item.status for item in exact.items] == ["expired"]


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


@pytest.mark.django_db(databases=["default", "owner"])
def test_a_rejected_send_says_what_its_error_means() -> None:
    tenant = Tenant.objects.using("owner").create(
        id=uuid.uuid7(),
        slug="test",
        name="Test",
        pack="toy",
        status="active",
        timezone="UTC",
        synced_at=timezone.now(),
    )
    contact = Contact.objects.using("owner").create(tenant=tenant, channel="main", external_id="1")
    rejected = OutboundMessage.objects.using("owner").create(
        tenant=tenant,
        contact=contact,
        channel="main",
        kind="proactive",
        idem_key="r",
        status="failed",
        last_error="status failed: 131047",
    )
    facts = activity_detail("outbound", str(rejected.pk), actor="operador").facts
    # The raw error, then what it means and what to do (as in Incidencias).
    assert facts[:3] == [
        "Error: status failed: 131047",
        "Motivo: Fuera de la ventana de 24 h",
        "Qué hacer: Fuera de la ventana de 24 h de WhatsApp: solo se puede escribir con una"
        " plantilla aprobada. Reintentar no sirve.",
    ]
    OutboundMessage.objects.using("owner").filter(pk=rejected.pk).update(
        status="unknown", last_error="interrupted while sending"
    )
    facts = activity_detail("outbound", str(rejected.pk), actor="operador").facts
    assert facts == ["Error: interrupted while sending"]  # ambiguous: no rejection to explain
