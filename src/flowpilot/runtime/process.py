"""`process_event` and `apply_status`.

`process_event` runs one contact message in three steps, so no transaction is open
while the pack calls Calendar or the adapter calls the provider:

1. tx1: load the event (done if it is no longer `pending`), upsert the contact and load
   its conversation with the effective state (expiry and version).
2. No transaction: acknowledge, then the contact limit, a global command or the pack.
3. tx2: save the state, create the outbound messages and the actions, mark the event and
   queue the sends; the jobs exist only if it commits.

Reprocessing an event is safe: replies are created only in tx2, and tx2 does nothing if
another run already finished the event.
"""

import copy
import dataclasses
import logging
import re
from typing import Any
from uuid import UUID

from django.conf import settings
from django.db.models import F, Q
from django.utils import timezone

from core.actions import Action, NotifyOwner, SendProactive, UpdateContact
from core.conversation import (
    EffectiveState,
    effective_state,
    global_command,
    menu_message,
    opt_result,
    recovery_result,
)
from core.errors import TransientError
from core.limits import plan_sends
from core.messages import IncomingMessage
from core.pack import ContactInfo, PackResult
from core.proactive import ProactiveMessage
from core.replies import Text
from flowpilot.channels.adapters import endpoint
from flowpilot.channels.base import InboundItem, StatusItem, parse_stored
from flowpilot.channels.ratelimit import WindowLimiter
from flowpilot.jobs import OUTBOUND, SEND_NOTIFICATION, app
from flowpilot.ops.logging import bind, contextual
from flowpilot.ops.state import record
from flowpilot.runtime.context import CalendarFactory, build_context, google_calendar
from flowpilot.runtime.identity import aliases_for, phone_group, phone_key
from flowpilot.runtime.models import (
    Channel,
    Contact,
    Conversation,
    InboundEvent,
    Notification,
    OutboundMessage,
)
from flowpilot.runtime.outbound import create_proactive, create_replies, defer_sends
from flowpilot.tenancy.registry import LoadedTenant, get_registry
from flowpilot.tenancy.schema import PHONE
from flowpilot.tenancy.tx import tenant_tx

log = logging.getLogger(__name__)

# What the contacts of a degraded tenant receive: its pack cannot run.
UNAVAILABLE_TEXT = "Ahora mismo no puedo atenderte; inténtalo más tarde."

# More than 20 messages in 60 s from one contact are saved and not answered. The
# worker is a single process, so an in-memory window covers all its threads.
contact_limiter = WindowLimiter(limit=20, window_s=60)

Status = InboundEvent.Status
Sent = OutboundMessage.Status


@contextual
def process_event(
    tenant_id: UUID,
    event_id: UUID,
    *,
    last_attempt: bool,
    first_attempt: bool = True,
    calendars: CalendarFactory = google_calendar,
) -> None:
    tenant = get_registry().by_id.get(tenant_id)
    if tenant is None:  # removed from tenants/ after the event was saved
        log.error("process_event of an unknown tenant %s: event left pending", tenant_id)
        return
    now = timezone.now()

    # ── tx1: load ─────────────────────────────────────────────────────────
    with tenant_tx(tenant.id):
        event = InboundEvent.objects.filter(id=event_id).first()
        if event is None or event.status != Status.PENDING:
            return  # already processed: a retry after tx2 committed
        bind(tenant=tenant.slug, channel=event.channel, event_id=str(event.id))
        ep = endpoint(tenant, event.channel)
        item = parse_stored(ep.adapter, _payload(event), ep.channel)
        if not isinstance(item, InboundItem):
            raise ValueError(f"event {event.id} holds no message")
        # The time it reached us: a Telegram callback has no date of its own.
        message = dataclasses.replace(item.message, received_at=event.received_at)
        contact = _upsert_contact(tenant, event.channel, item, now)
        conversation, _ = Conversation.objects.get_or_create(tenant_id=tenant.id, contact=contact)
        effective = _effective_state(tenant, conversation, now)

    # ── No transaction: acknowledge, then the pack ────────────────────────
    try:
        ep.adapter.acknowledge(_payload(event), ep.channel, ep.secrets)
    except Exception as e:  # never stops the message
        log.warning("acknowledge failed for event %s: %s", event.id, type(e).__name__)

    state = effective.state
    notices = effective.notices
    error = ""
    keep_conversation = False  # True: the conversation row is left as it was
    command = global_command(message)
    # A retried event was already counted on its first attempt.
    over_limit = contact_limiter.hit(str(contact.id)) if first_attempt else False
    if over_limit:
        log.warning("contact over its message limit: event %s saved, not answered", event.id)
        result, notices, keep_conversation = PackResult(), [], True
    elif tenant.pack is None or tenant.is_degraded:
        # Its conversation is left untouched, to go on once the tenant is fixed.
        result, notices, keep_conversation = PackResult([Text(UNAVAILABLE_TEXT)]), [], True
    elif command == "opt_out" or command == "opt_in":
        result = opt_result(command)
    else:
        if command == "menu":
            state, message = {}, menu_message(message.received_at)
        result, error = _run_pack(
            tenant, event, contact, state, message, last_attempt=last_attempt, calendars=calendars
        )

    # ── tx2: persist ──────────────────────────────────────────────────────
    with tenant_tx(tenant.id):
        event = InboundEvent.objects.select_for_update().get(id=event_id)
        if event.status != Status.PENDING:
            return  # another run finished it meanwhile: never answer twice
        contact.refresh_from_db()
        if not keep_conversation:
            assert tenant.pack is not None
            conversation.state = state if result.state is None else result.state
            conversation.state_version = tenant.pack.state_version
            conversation.last_inbound_at = now
            conversation.save(
                update_fields=["state", "state_version", "last_inbound_at", "updated_at"]
            )
        replies = plan_sends([*notices, *result.replies])
        messages = create_replies(tenant.id, contact, event, replies)
        messages += apply_actions(
            tenant, event.channel, result.actions, contact=contact, event=event, now=now
        )
        event.status = Status.FAILED if error else Status.DONE
        event.error = error
        event.processed_at = now
        event.save(update_fields=["status", "error", "processed_at"])
        defer_sends(tenant.id, messages)


def _run_pack(
    tenant: LoadedTenant,
    event: InboundEvent,
    contact: Contact,
    state: dict[str, Any],
    message: IncomingMessage,
    *,
    last_attempt: bool,
    calendars: CalendarFactory,
) -> tuple[PackResult, str]:
    """The pack's result and, if it failed, the error recorded on the event. A
    `TransientError` is retried by the job; on the last attempt, and on any other
    exception, the contact gets the recovery text and the state is reset."""
    assert tenant.pack is not None
    try:
        ctx = build_context(
            tenant,
            Channel(event.channel),
            contact=_contact_info(contact),
            # A copy: a pack that mutates ctx.state must not change what tx2 saves when it
            # returns state=None (the harness does the same).
            state=copy.deepcopy(state),
            event_id=event.id,
            calendars=calendars,
        )
        result = tenant.pack.handle_message(ctx, message)
        record(tenant.id, event.channel, failed=False)
        return result, ""
    except TransientError:
        record(tenant.id, event.channel, failed=True)
        if not last_attempt:
            raise
        log.warning("event %s: transient error on the last attempt", event.id)
        return recovery_result(), "TransientError on the last attempt"
    except Exception as e:
        record(tenant.id, event.channel, failed=True)
        # Sentry, once configured takes it from this log record.
        log.exception("event %s: unexpected error in pack %s", event.id, tenant.pack.name)
        return recovery_result(), type(e).__name__


def apply_actions(
    tenant: LoadedTenant,
    channel: str,
    actions: list[Action],
    *,
    contact: Contact | None,
    event: InboundEvent | None,
    now: Any,
) -> list[OutboundMessage]:
    """Apply a pack's actions inside the caller's tenant_tx. `channel` is where they come
    from: a test conversation never reaches the main channel nor the owner.
    Returns the proactive messages to send."""
    messages: list[OutboundMessage] = []
    for action in actions:
        match action:
            case UpdateContact():
                if contact is None:
                    log.warning("UpdateContact without a contact ignored")
                    continue
                if action.display_name is not None:
                    contact.display_name = action.display_name[:200]
                if action.opt_out is not None:
                    contact.opt_out = action.opt_out
                    contact.opt_out_at = now if action.opt_out else None
                contact.save(update_fields=["display_name", "opt_out", "opt_out_at"])
            case SendProactive():
                target = _proactive_target(tenant, channel, action)
                if target is None:
                    continue
                proactive = ProactiveMessage(action.template, action.params, action.button_payloads)
                row = create_proactive(tenant.id, target, proactive, action.idem_key, event)
                if row is not None:
                    messages.append(row)
            case NotifyOwner():
                _notify_owner(tenant, channel, action)
    return messages


def _proactive_target(tenant: LoadedTenant, channel: str, action: SendProactive) -> Contact | None:
    """The contact a proactive message goes to, by its own channel, or None if it
    must not be sent: unknown, opted out, unreachable, or on another channel than the one
    the action came from."""
    ref = action.to
    if ref.contact_id is not None:
        target = Contact.objects.filter(id=ref.contact_id).first()
    else:
        target = _contact_by_phone(tenant, channel, str(ref.phone))
    if target is None:
        log.info("proactive %s not sent: no contact for it", action.template.name)
        return None
    if target.channel != channel:
        log.warning("proactive %s not sent: contact of another channel", action.template.name)
        return None
    if channel == Channel.TEST:
        allowed = {str(user) for user in settings.TEST_BOT_OPERATORS}
        if target.external_id not in allowed:
            log.info("test proactive not sent: contact no longer has access to this tenant")
            return None
    if (
        channel == Channel.MAIN
        and tenant.file.channel is not None
        and tenant.file.channel.type == "whatsapp"
    ):
        number = phone_key(
            target.phone_e164 or (target.external_id if target.external_id.isdecimal() else "")
        )
        if number and any(c.opt_out or c.unreachable for c in phone_group(tenant.id, number)):
            log.info("proactive not sent: linked phone identity opted out or is unreachable")
            return None
    if target.opt_out or target.unreachable:
        log.info("proactive %s not sent: contact opted out or unreachable", action.template.name)
        return None
    return target


def _contact_by_phone(tenant: LoadedTenant, channel: str, phone: str) -> Contact | None:
    """A phone with no contact yet (manual bookings): only on a WhatsApp main
    channel; elsewhere it is logged and not sent."""
    digits = re.sub(r"[\s+]", "", phone)
    if (
        channel != Channel.MAIN
        or tenant.file.channel is None
        or tenant.file.channel.type != "whatsapp"
    ):
        log.info("proactive to a phone not sent: only possible on a WhatsApp main channel")
        return None
    if not PHONE.match(digits):
        log.warning("proactive to a malformed phone not sent")
        return None
    e164 = f"+{digits}"
    same_phone = list(
        Contact.objects.filter(channel=Channel.MAIN)
        .filter(Q(phone_e164=e164) | Q(external_id=digits))
        .order_by(F("last_activity_at").desc(nulls_last=True))
    )
    if any(c.opt_out or c.unreachable for c in same_phone):
        # The same person may have a BSUID contact and one made from the phone: an
        # opt-out on either one counts.
        log.info("proactive to a phone not sent: that phone opted out or is unreachable")
        return None
    if same_phone:
        return same_phone[0]
    contact, _ = Contact.objects.get_or_create(
        tenant_id=tenant.id,
        channel=Channel.MAIN,
        external_id=digits,
        defaults={"phone_e164": e164},
    )
    return contact


def _notify_owner(tenant: LoadedTenant, channel: str, action: NotifyOwner) -> None:
    """Queue the notice if the owner has a chat and wants this kind; otherwise it
    is only logged. A notice born in the test channel never reaches the owner: it goes to
    the ops chat with "🧪", whatever the owner settings. Delivery is
    `send_notification`, which reads `audience`."""
    owner = tenant.file.owner
    if channel == Channel.MAIN:
        if owner is None or owner.telegram_chat_id is None or action.kind not in owner.notify:
            log.info("NotifyOwner %s only logged: the owner does not receive it", action.kind)
            return
        audience, text = Notification.Audience.OWNER, action.text
    else:
        audience, text = Notification.Audience.OPS, f"🧪 {tenant.file.name}: {action.text}"
    row = Notification(
        tenant_id=tenant.id,
        idem_key=action.idem_key,
        audience=audience,
        kind=action.kind[:64],
        text=text,
    )
    Notification.objects.bulk_create([row], ignore_conflicts=True)
    if Notification.objects.filter(id=row.id).exists():
        app.configure_task(SEND_NOTIFICATION, queue=OUTBOUND, lock=f"owner:{tenant.id}").defer(
            tenant_id=str(tenant.id), notification_id=str(row.id)
        )


@contextual
def apply_status(tenant_id: UUID, event_id: UUID) -> None:
    """A delivery status from the provider updates its outbound_message: found by
    `outbound_ref` (our id) or by the provider's id."""
    tenant = get_registry().by_id.get(tenant_id)
    if tenant is None:
        log.error("apply_status of an unknown tenant %s: event left pending", tenant_id)
        return
    with tenant_tx(tenant.id):
        event = InboundEvent.objects.select_for_update().filter(id=event_id).first()
        if event is None or event.status != Status.PENDING:
            return
        bind(tenant=tenant.slug, channel=event.channel, event_id=str(event.id))
        ep = endpoint(tenant, event.channel)
        item = parse_stored(ep.adapter, _payload(event), ep.channel)
        if not isinstance(item, StatusItem):
            raise ValueError(f"event {event.id} holds no status")
        message = _outbound_of(item)
        if message is None:
            log.info("status for an unknown outbound message (event %s)", event.id)
        else:
            _update_from_status(message, item)
        event.status = Status.DONE
        event.processed_at = timezone.now()
        event.save(update_fields=["status", "processed_at"])


def _outbound_of(item: StatusItem) -> OutboundMessage | None:
    if item.outbound_ref:
        try:
            ref = UUID(item.outbound_ref)
        except ValueError:
            ref = None
        if ref is not None:
            found = OutboundMessage.objects.select_for_update().filter(id=ref).first()
            if found is not None:
                return found
    return (
        OutboundMessage.objects.select_for_update()
        .filter(provider_message_id=item.provider_message_id)
        .first()
    )


def _update_from_status(message: OutboundMessage, item: StatusItem) -> None:
    """`sent`, `delivered` and `read` prove the message left: an `unknown` (or a status
    that overtook our own `sent`) becomes `sent`. `failed` turns a sent message into
    `failed`. Pricing is kept whenever it comes."""
    if item.status == "failed":
        if message.status in (Sent.SENT, Sent.UNKNOWN, Sent.SENDING):
            message.status = Sent.FAILED
            message.last_error = f"status failed: {item.error or '?'}"
    elif message.status != Sent.FAILED:
        message.status = Sent.SENT
        message.sent_at = message.sent_at or timezone.now()
    message.provider_message_id = message.provider_message_id or item.provider_message_id
    if item.pricing_category is not None:
        message.pricing_category = item.pricing_category
    if item.billable is not None:
        message.billable = item.billable
    message.save(
        update_fields=[
            "status",
            "last_error",
            "sent_at",
            "provider_message_id",
            "pricing_category",
            "billable",
        ]
    )


def _upsert_contact(tenant: LoadedTenant, channel: str, item: InboundItem, now: Any) -> Contact:
    """By (tenant, channel, external_id). The phone is refreshed when the provider gives
    it; the provider's name only fills an empty one, so a name the pack set (UpdateContact)
    is kept."""
    contact, created = Contact.objects.get_or_create(
        tenant_id=tenant.id,
        channel=channel,
        external_id=item.external_id,
        defaults={
            "phone_e164": item.phone,
            "display_name": item.display_name or "",
            "last_activity_at": now,
        },
    )
    if not created:
        if item.phone:
            contact.phone_e164 = item.phone
        if item.display_name and not contact.display_name:
            contact.display_name = item.display_name
        contact.last_activity_at = now
        contact.save(update_fields=["phone_e164", "display_name", "last_activity_at"])
    return contact


def _effective_state(tenant: LoadedTenant, conversation: Conversation, now: Any) -> EffectiveState:
    if tenant.pack is None or tenant.is_degraded:
        return EffectiveState(dict(conversation.state or {}))
    effective = effective_state(
        conversation.state or {},
        conversation.state_version,
        conversation.last_inbound_at,
        pack_state_version=tenant.pack.state_version,
        timeout_min=tenant.pack.conversation_timeout_min,
        now=now,
    )
    if effective.reset == "version":
        log.info("conversation state reset: the pack's state_version changed")
    return effective


def _contact_info(contact: Contact) -> ContactInfo:
    with tenant_tx(contact.tenant_id):
        aliases = aliases_for(contact)
    return ContactInfo(
        id=contact.id,
        external_id=contact.external_id,
        phone=contact.phone_e164,
        display_name=contact.display_name or None,
        opt_out=contact.opt_out,
        alias_ids=aliases,
    )


def _payload(event: InboundEvent) -> dict[str, Any]:
    if not isinstance(event.payload, dict):
        raise ValueError(f"event {event.id} has no payload")
    return event.payload
