"""Synchronous operator exports and erasure; never pass customer data to jobs."""

import json
import os
from pathlib import Path
from typing import Any
from uuid import UUID

from django.core.management.base import CommandError
from django.db import transaction
from django.db.models import Q, QuerySet

from flowpilot.runtime.models import (
    DEMO_CHANNELS,
    Contact,
    Conversation,
    DemoEvent,
    DemoSession,
    InboundEvent,
    Notification,
    OutboundMessage,
)
from flowpilot.tenancy.models import Tenant

MODELS = (Contact, Conversation, InboundEvent, OutboundMessage, Notification, DemoSession)


def tenant_for(slug: str) -> Tenant:
    tenant = Tenant.objects.using("owner").filter(slug=slug).first()
    if tenant is None:
        raise CommandError("Tenant desconocido.")
    return tenant


def contact_for(tenant: Tenant, external_id: str, channel: str | None) -> Contact:
    query = Contact.objects.using("owner").filter(tenant=tenant, external_id=external_id)
    if channel:
        query = query.filter(channel=channel)
    contacts = list(query[:2])
    if not contacts:
        raise CommandError("Contacto desconocido.")
    if len(contacts) > 1:
        raise CommandError("Identificador ambiguo: indique --channel main, demo_tg o demo_wa.")
    return contacts[0]


def _senders(payload: object) -> set[str]:
    """Extract only identity fields of stored Telegram and single-item WhatsApp bodies.

    Do not parse arbitrary message text, and do not log malformed/expired payloads.
    """
    if not isinstance(payload, dict):
        return set()
    identities: set[str] = set()
    for key in ("message", "callback_query"):
        part = payload.get(key)
        if isinstance(part, dict) and isinstance(part.get("from"), dict):
            identities.add(str(part["from"].get("id", "")))
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            for message in value.get("messages", []):
                for field in ("from_user_id", "user_id", "from"):
                    if isinstance(message.get(field), str):
                        identities.add(message[field])
            for status in value.get("statuses", []):
                for field in ("recipient_id", "recipient_user_id"):
                    if isinstance(status.get(field), str):
                        identities.add(status[field])
    return identities


def contact_events(contact: Contact) -> set[UUID]:
    outbound = OutboundMessage.objects.using("owner").filter(
        tenant_id=contact.tenant_id, contact=contact
    )
    ids = set(outbound.exclude(inbound_event=None).values_list("inbound_event_id", flat=True))
    provider_ids = set(
        outbound.exclude(provider_message_id=None).values_list("provider_message_id", flat=True)
    )
    outbound_ids = {str(pk) for pk in outbound.values_list("id", flat=True)}
    identities = {contact.external_id}
    if contact.phone_e164:
        identities.add(contact.phone_e164.lstrip("+"))
    events = InboundEvent.objects.using("owner").filter(
        tenant_id=contact.tenant_id, channel=contact.channel
    )
    for event in events.iterator(chunk_size=1000):
        if identities & _senders(event.payload):
            ids.add(event.id)
        # Delivery statuses also identify the outgoing message, even without a recipient.
        if isinstance(event.payload, dict):
            for entry in event.payload.get("entry", []):
                for change in entry.get("changes", []):
                    for status in change.get("value", {}).get("statuses", []):
                        if (
                            status.get("id") in provider_ids
                            or status.get("biz_opaque_callback_data") in outbound_ids
                        ):
                            ids.add(event.id)
    return ids


def demo_events(tenant_id: UUID, event_ids: set[UUID] | None = None) -> QuerySet[DemoEvent]:
    events = InboundEvent.objects.using("owner").filter(
        tenant_id=tenant_id, channel__in=DEMO_CHANNELS
    )
    if event_ids is not None:
        events = events.filter(id__in=event_ids)
    keys: set[tuple[str, str]] = set()
    for channel, provider_id in events.values_list("channel", "provider_event_id").iterator(
        chunk_size=1000
    ):
        keys.add((channel, provider_id.removeprefix("select:")))
    if not keys:
        return DemoEvent.objects.none()
    query = Q()
    for channel, raw in keys:
        query |= Q(channel=channel, provider_event_id=raw)
    return DemoEvent.objects.using("owner").filter(query)


def export_data(tenant: Tenant, contact: Contact | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {"tenant": tenant.slug, "data": {}}
    for model in MODELS:
        query: QuerySet[Any] = model.objects.using("owner").filter(tenant_id=tenant.id)
        if contact is not None:
            if model is Contact:
                query = query.filter(id=contact.id)
            elif model in (Conversation, OutboundMessage):
                query = query.filter(contact_id=contact.id)
            elif model is InboundEvent:
                query = query.filter(id__in=contact_events(contact))
            elif model is DemoSession and contact.channel in DEMO_CHANNELS:
                query = query.filter(channel=contact.channel, external_id=contact.external_id)
            else:
                query = query.none()
        result["data"][model._meta.db_table] = list(query.values())
    result["data"]["demo_event"] = (
        list(demo_events(tenant.id, contact_events(contact) if contact else None).values())
        if contact is None or contact.channel in DEMO_CHANNELS
        else []
    )
    return result


def write_private(path: str, data: dict[str, Any]) -> None:
    """Exclusive creation prevents accidental disclosure through existing files/symlinks."""
    try:
        descriptor = os.open(Path(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            json.dump(data, output, default=str, ensure_ascii=False)
            output.write("\n")
    except OSError:
        raise CommandError("No se pudo crear el archivo privado de exportación.") from None


def forget(contact: Contact) -> None:
    with transaction.atomic(using="owner"):
        ids = contact_events(contact)
        if contact.channel in DEMO_CHANNELS:
            demo_events(contact.tenant_id, ids).delete()
        InboundEvent.objects.using("owner").filter(tenant_id=contact.tenant_id, id__in=ids).delete()
        if contact.channel in DEMO_CHANNELS:
            DemoSession.objects.using("owner").filter(
                channel=contact.channel, external_id=contact.external_id
            ).delete()
        Contact.objects.using("owner").filter(tenant_id=contact.tenant_id, id=contact.id).delete()


def purge(tenant: Tenant) -> None:
    with transaction.atomic(using="owner"):
        demo_events(tenant.id).delete()
        for model in MODELS:
            model.objects.using("owner").filter(tenant_id=tenant.id).delete()
