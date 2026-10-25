"""Outbound messages (design.md §7.4, §8.2): the rows of `outbound_message`, the jobs that
send them and `send_message` itself.

Rows and jobs are created inside the transaction that commits them, so a send job exists
only if its message does.
"""

import logging
from uuid import UUID

from django.utils import timezone

from core.proactive import ProactiveMessage
from core.replies import Reply
from core.serialization import dump_outbound, load_outbound
from flowpilot.channels.adapters import endpoint
from flowpilot.channels.base import Ambiguous, Rejected, RetryLater, SendOutcome, Sent
from flowpilot.jobs import OUTBOUND, SEND_MESSAGE, app
from flowpilot.ops.logging import bind, contextual
from flowpilot.runtime.locks import contact_hash
from flowpilot.runtime.models import Contact, InboundEvent, OutboundMessage
from flowpilot.tenancy.registry import get_registry
from flowpilot.tenancy.tx import tenant_tx

log = logging.getLogger(__name__)

Status = OutboundMessage.Status


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


# ── send_message (§7.4) ───────────────────────────────────────────────────

MAX_SEND_ATTEMPTS = 5


class SendRetry(Exception):
    """The provider asked to retry later: the job is retried (§7.5), keeping its place
    before the contact's later messages (same lock, older job)."""

    def __init__(self, after_s: float | None) -> None:
        super().__init__(f"retry in {after_s} s" if after_s is not None else "retry")
        self.after_s = after_s


@contextual
def send_message(tenant_id: UUID, outbound_id: UUID) -> None:
    """Send one outbound message, never twice: the attempt is committed as `sending`
    before calling the provider, so a run cut in the middle is found as `sending` and
    left `unknown` instead of resent blindly."""
    tenant = get_registry().by_id.get(tenant_id)
    if tenant is None:
        log.error("send_message of an unknown tenant %s: message left as it is", tenant_id)
        return

    with tenant_tx(tenant.id):
        message = OutboundMessage.objects.select_for_update().filter(id=outbound_id).first()
        if message is not None:
            bind(
                tenant=tenant.slug,
                channel=message.channel,
                event_id=str(message.inbound_event_id or ""),
            )
        if message is None or message.status in (Status.SENT, Status.UNKNOWN, Status.FAILED):
            return  # done, or never resent blindly
        if message.status == Status.SENDING:
            message.status = Status.UNKNOWN
            message.unknown_at = timezone.now()
            message.last_error = "interrupted while sending"
            message.save(update_fields=["status", "last_error", "unknown_at"])
            log.warning("message %s was cut while sending: left unknown", message.id)
            return
        contact = message.contact
        if message.payload is None:
            message.status, message.last_error = Status.FAILED, "other: payload expired"
            message.save(update_fields=["status", "last_error", "unknown_at"])
            return
        # Everything that may fail before the call happens while still `pending`: an error
        # here rolls back and leaves the message as it was (the job fails, ops sees it).
        ep = endpoint(tenant, message.channel)
        rendered = ep.adapter.render(load_outbound(message.payload), ep.channel)
        message.status = Status.SENDING
        message.attempts += 1
        message.save(update_fields=["status", "attempts"])

    # No transaction while the provider answers.
    if ep.secrets is None:
        outcome: SendOutcome = Rejected("main channel disabled", "other")
    else:
        outcome = ep.adapter.send(rendered, _recipient(contact), ep.channel, ep.secrets, message.id)

    with tenant_tx(tenant.id):
        message = OutboundMessage.objects.select_for_update().get(id=outbound_id)
        if message.status != Status.SENDING:
            # A delivery status got here first (apply_status): it knows better.
            if isinstance(outcome, Sent) and not message.provider_message_id:
                message.provider_message_id = outcome.provider_message_id
                message.save(update_fields=["provider_message_id"])
            return
        retry = _record(tenant.slug, message, outcome)
    if retry is not None:
        raise retry


def _record(slug: str, message: OutboundMessage, outcome: SendOutcome) -> SendRetry | None:
    """Save the outcome; returns the exception that makes the job retry, if any."""
    fields = ["status", "last_error", "unknown_at"]
    match outcome:
        case Sent():
            message.status = Status.SENT
            message.provider_message_id = outcome.provider_message_id
            message.sent_at = timezone.now()
            message.last_error = ""
            fields += ["provider_message_id", "sent_at"]
        case Rejected():
            message.status = Status.FAILED
            message.last_error = f"{outcome.kind}: {outcome.reason}"
            if outcome.kind == "recipient":
                Contact.objects.filter(id=message.contact_id).update(unreachable=True)
            elif outcome.kind == "auth":
                # The 🔴 alert is sent by ops_check (T-6.1, §15.3), which looks for these.
                log.error("ALERT tenant %s: channel token rejected (%s)", slug, outcome.reason)
        case RetryLater() if message.attempts < MAX_SEND_ATTEMPTS:
            message.status = Status.PENDING
            message.last_error = "retry later"
            message.save(update_fields=fields)
            return SendRetry(outcome.after_s)
        case RetryLater():
            message.status = Status.FAILED
            message.last_error = f"other: still refused after {message.attempts} attempts"
        case Ambiguous():
            message.status = Status.UNKNOWN
            message.unknown_at = timezone.now()
            message.last_error = outcome.reason
    message.save(update_fields=fields)
    return None


def _recipient(contact: Contact) -> str:
    """WhatsApp: the phone when known, else the BSUID; Telegram: the chat (user) id."""
    if contact.phone_e164:
        return contact.phone_e164
    return contact.external_id
