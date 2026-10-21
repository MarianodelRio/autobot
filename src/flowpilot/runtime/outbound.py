"""Outbound messages: rows of `outbound_message` and the jobs that send them
(design.md §7.4, §8.2). Called inside the transaction that commits them, so a send job
exists only if its message does. `send_message` itself arrives with T-3.6."""

from uuid import UUID

from core.proactive import ProactiveMessage
from core.replies import Reply
from core.serialization import dump_outbound
from flowpilot.jobs import OUTBOUND, SEND_MESSAGE, app
from flowpilot.runtime.locks import contact_hash
from flowpilot.runtime.models import Contact, InboundEvent, OutboundMessage


def create_replies(
    tenant_id: UUID, contact: Contact, event: InboundEvent, replies: list[Reply]
) -> list[OutboundMessage]:
    """One row per planned reply, in order: `idem_key = reply:<event_id>:<seq>`."""
    rows = [
        OutboundMessage(
            tenant_id=tenant_id,
            contact=contact,
            channel=contact.channel,
            idem_key=f"reply:{event.id}:{seq}",
            seq=seq,
            kind=OutboundMessage.Kind.REPLY,
            payload=dump_outbound(reply),
            inbound_event=event,
        )
        for seq, reply in enumerate(replies)
    ]
    return OutboundMessage.objects.bulk_create(rows)


def create_proactive(
    tenant_id: UUID,
    contact: Contact,
    message: ProactiveMessage,
    idem_key: str,
    event: InboundEvent | None,
) -> OutboundMessage | None:
    """A proactive message with the pack's idempotency key; None if that key was already
    used (a sweep seeing the same appointment again, or a retried event)."""
    row = OutboundMessage(
        tenant_id=tenant_id,
        contact=contact,
        channel=contact.channel,
        idem_key=idem_key,
        kind=OutboundMessage.Kind.PROACTIVE,
        payload=dump_outbound(message),
        inbound_event=event,
    )
    OutboundMessage.objects.bulk_create([row], ignore_conflicts=True)
    return row if OutboundMessage.objects.filter(id=row.id).exists() else None


def defer_sends(tenant_id: UUID, messages: list[OutboundMessage]) -> None:
    """Queue `send_message` for each message, in order, with the contact's `out:<h>` lock:
    a contact's messages leave one at a time and in order."""
    for message in messages:
        contact = message.contact
        lock = f"out:{contact_hash(tenant_id, contact.channel, contact.external_id)}"
        app.configure_task(SEND_MESSAGE, queue=OUTBOUND, lock=lock).defer(
            tenant_id=str(tenant_id), outbound_id=str(message.id)
        )
