"""Contact search and audited conversation detail."""

from datetime import datetime
from typing import Any
from uuid import UUID

from django.db import transaction
from django.db.models import Q
from django.http import HttpRequest
from django.shortcuts import get_object_or_404
from ninja import Router, Schema

from autobot.ops.audit import record
from autobot.panel.errors import ApiError
from autobot.panel.services.activity import (
    decode_cursor,
    describe_inbound,
    describe_outbound,
    encode_cursor,
)
from autobot.runtime.models import Contact, Conversation, OutboundMessage
from autobot.tenancy.models import Tenant

router = Router(tags=["contacts"])


class ContactOut(Schema):
    id: UUID
    tenant: str
    channel: str
    external_id: str
    phone_e164: str | None
    display_name: str
    opt_out: bool
    unreachable: bool
    last_activity_at: datetime | None
    created_at: datetime


def contact_out(contact: Contact) -> ContactOut:
    return ContactOut(
        id=contact.id,
        tenant=contact.tenant.slug,
        channel=contact.channel,
        external_id=contact.external_id,
        phone_e164=contact.phone_e164,
        display_name=contact.display_name,
        opt_out=contact.opt_out,
        unreachable=contact.unreachable,
        last_activity_at=contact.last_activity_at,
        created_at=contact.created_at,
    )


class ContactPage(Schema):
    items: list[ContactOut]
    next_cursor: str | None


class Exchange(Schema):
    inbound_id: UUID | None
    inbound_at: datetime | None
    inbound: str | None
    outbound_id: UUID
    outbound_at: datetime
    outbound: str
    status: str


class ContactDetail(Schema):
    contact: ContactOut
    exchanges: list[Exchange]
    state: dict[str, Any] | None


@router.get("/tenants/{slug}/contacts", response=ContactPage)
def contacts(
    request: HttpRequest,
    slug: str,
    search: str = "",
    cursor: str = "",
    limit: int = 50,
) -> ContactPage:
    limit = max(1, min(limit, 100))
    tenant = get_object_or_404(Tenant.objects.using("owner"), slug=slug)
    qs = Contact.objects.using("owner").filter(tenant=tenant).select_related("tenant")
    if search:
        qs = qs.filter(
            Q(display_name__icontains=search)
            | Q(phone_e164__icontains=search)
            | Q(external_id__icontains=search)
        )
    if cursor:
        at, rank, id = decode_cursor(cursor)
        if rank != 0:
            raise ApiError("bad_request", "Cursor no válido.", 400)
        qs = qs.filter(Q(created_at__lt=at) | Q(created_at=at, id__lt=id))
    rows = list(qs.order_by("-created_at", "-id")[: limit + 1])
    page = rows[:limit]
    return ContactPage(
        items=[contact_out(c) for c in page],
        next_cursor=encode_cursor(page[-1].created_at, 0, str(page[-1].id))
        if len(rows) > limit
        else None,
    )


@router.get("/contacts/{id}", response=ContactDetail)
def contact_detail(request: HttpRequest, id: UUID) -> ContactDetail:
    contact = get_object_or_404(Contact.objects.using("owner").select_related("tenant"), pk=id)
    record(
        actor=request.user.username,
        action="contact.view",
        summary="Consulta de contacto",
        tenant_id=contact.tenant_id,
        target_type="contact",
        target_id=str(contact.id),
        details={"contact_id": str(contact.id)},
    )
    messages = (
        OutboundMessage.objects.using("owner")
        .filter(contact=contact)
        .select_related("inbound_event")
        .order_by("-created_at", "-id")[:50]
    )
    return ContactDetail(
        contact=contact_out(contact),
        state=(
            Conversation.objects.using("owner")
            .filter(tenant_id=contact.tenant_id, contact=contact)
            .values_list("state", flat=True)
            .first()
        ),
        exchanges=[
            Exchange(
                inbound_id=m.inbound_event_id,
                inbound_at=m.inbound_event.received_at if m.inbound_event else None,
                inbound=describe_inbound(m.inbound_event.channel, m.inbound_event.payload)
                if m.inbound_event
                else None,
                outbound_id=m.id,
                outbound_at=m.created_at,
                outbound=describe_outbound(m.payload),
                status=m.status,
            )
            for m in messages
        ],
    )


class ContactExportOut(Schema):
    tenant: str
    data: dict[str, Any]


@router.get("/contacts/{id}/export", response=ContactExportOut)
def contact_export(request: HttpRequest, id: UUID) -> ContactExportOut:
    """C16: the panel equivalent of `contact_export`, downloaded as JSON instead
    of written to an operator-chosen local path."""
    from autobot.runtime import privacy

    contact = get_object_or_404(Contact.objects.using("owner").select_related("tenant"), pk=id)
    with transaction.atomic(using="owner"):
        data = privacy.export_data(contact.tenant, contact)
    record(
        actor=request.user.username,
        action="contact.export",
        summary="Exportación de datos del contacto",
        tenant_id=contact.tenant_id,
        target_type="contact",
        target_id=str(contact.id),
        details={"contact_id": str(contact.id)},
    )
    return ContactExportOut(**data)


class ContactForgetOut(Schema):
    forgotten: bool = True


@router.post("/contacts/{id}/forget", response=ContactForgetOut)
def contact_forget(request: HttpRequest, id: UUID) -> ContactForgetOut:
    """C16: the panel equivalent of `contact_forget` (right to erasure)."""
    from autobot.runtime import privacy

    contact = get_object_or_404(Contact.objects.using("owner").select_related("tenant"), pk=id)
    tenant_id, contact_id = contact.tenant_id, contact.id
    # The erasure and its audit row commit together: never an erasure without a trace.
    with transaction.atomic(using="owner"):
        privacy.forget(contact)
        record(
            actor=request.user.username,
            action="contact.forget",
            summary="Contacto olvidado (derecho de supresión)",
            tenant_id=tenant_id,
            target_type="contact",
            target_id=str(contact_id),
            details={"contact_id": str(contact_id)},
        )
    return ContactForgetOut()
