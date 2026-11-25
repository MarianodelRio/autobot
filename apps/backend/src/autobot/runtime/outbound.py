"""Outbound messages: the rows of `outbound_message`, the jobs that
send them and `send_message` itself.

Rows and jobs are created inside the transaction that commits them, so a send job exists
only if its message does.
"""

import logging
import random
from datetime import datetime, timedelta
from uuid import UUID

from django.db.models import Q
from django.utils import timezone

from autobot.channels.adapters import Endpoint, endpoint
from autobot.channels.base import Ambiguous, Rejected, RetryLater, SendOutcome, Sent
from autobot.ops import state
from autobot.ops.logging import bind, contextual
from autobot.runtime.breaker import PROBE_EVERY_S, ProviderBreaker
from autobot.runtime.cache import remember_demo_outbound
from autobot.runtime.jobs import OUTBOUND, SEND_MESSAGE
from autobot.runtime.locks import send_lock
from autobot.runtime.models import Channel, Contact, InboundEvent, OutboundMessage
from autobot.runtime.queue import enqueue
from autobot.tenancy.registry import tenant_by_id
from autobot.tenancy.tx import tenant_tx
from core.conversation import APOLOGY_TEXT
from core.proactive import ProactiveMessage
from core.replies import Reply, Text
from core.serialization import dump_outbound, load_outbound

log = logging.getLogger(__name__)

Status = OutboundMessage.Status

PROBE_WAIT_MAX_S = PROBE_EVERY_S

# While the breaker is open the messages wait for the next probe, each with a jitter on
# top, so when the provider comes back they are released gradually instead of all at the
# same second (a herd of hundreds of sends slowed every reply, of every provider, for
# minutes). A reply, which a person is waiting for, spreads over a short window; a
# reminder or any other proactive message waits longer, behind them.
REPLY_WAIT_SPREAD_S = (0.0, 30.0)
PROACTIVE_WAIT_SPREAD_S = (15.0, 90.0)

# Procrastinate runs the higher priority first among the ready jobs of a queue: replies
# before reminders when both are waiting for a slot of the outbound worker.
REPLY_PRIORITY = 10
PROACTIVE_PRIORITY = 0


def _signal(provider: str, is_open: bool) -> None:
    """The breaker opened or closed: tell ops_check. Never breaks a send."""
    try:
        state.record_provider(provider, is_open=is_open)
    except Exception:
        log.warning("could not record the state of the %s breaker", provider, exc_info=True)
    log.warning("provider %s breaker %s", provider, "opened" if is_open else "closed")


# One per outbound worker process; tests reset it (see tests/conftest.py).
BREAKER = ProviderBreaker(on_change=_signal)


# ── Time limits (ADR-024) ──────────────────────────────────────────

REPLY_TTL = timedelta(minutes=30)  # a reply later than this answers a conversation that moved on
PROACTIVE_TTL = timedelta(hours=24)  # at most; a pack's `not_after` may make it shorter
APOLOGY_TTL = timedelta(hours=6)
APOLOGY_EVERY = timedelta(hours=6)  # at most one apology per contact in this time
# WhatsApp only lets free text go out within 24 h of the contact's last message. A reply is
# created right after that message and expires in `REPLY_TTL`, and an apology comes at that
# moment and lasts `APOLOGY_TTL`: both always end inside the window, with an hour to spare.
assert timedelta(hours=23) >= REPLY_TTL + APOLOGY_TTL
APOLOGY_PREFIX = "apology:"
# `last_error` of a message the provider refused for its credentials (`_record`): once the
# token is fixed, a proactive one is revived like an expired one.
AUTH_FAILURE_PREFIX = "auth:"


# ── Ambiguous sends (ADR-026) ──────────────────────────────────────

# How long an `unknown` message waits for a delivery status (Meta's usually comes within
# minutes) before `reconcile_unknown` or a person may resend it.
RECONCILE_WAIT = timedelta(minutes=10)
MAX_AMBIGUOUS_RESENDS = 1

# Whether a duplicate of a message of this kind is harmless, so the platform may resend it
# once if still ambiguous after RECONCILE_WAIT. Replies, menus and apologies repeat a
# sentence the contact has already seen or was waiting for; a reminder repeats a reminder.
# A kind missing here is "unsafe": only a person resends it.
DUP_POLICY: dict[str, str] = {
    OutboundMessage.Kind.REPLY: "safe",
    OutboundMessage.Kind.PROACTIVE: "safe",
}
SAFE_DUP_KINDS = tuple(kind for kind, policy in DUP_POLICY.items() if policy == "safe")


def dup_policy(kind: str) -> str:
    return DUP_POLICY.get(kind, "unsafe")


def create_replies(
    tenant_id: UUID, contact: Contact, event: InboundEvent, replies: list[Reply]
) -> list[OutboundMessage]:
    """One row per planned reply, in order: `idem_key = reply:<event_id>:<seq>`. Each may
    be sent until `REPLY_TTL` from now."""
    expires_at = timezone.now() + REPLY_TTL
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
            expires_at=expires_at,
        )
        for seq, reply in enumerate(replies)
    ]
    return OutboundMessage.objects.bulk_create(rows)


def proactive_expiry(now: datetime, not_after: datetime | None) -> datetime:
    """Until when a proactive message may be retried: 24 h, or the pack's `not_after`
    if earlier."""
    limit = now + PROACTIVE_TTL
    return limit if not_after is None else min(limit, not_after)


def create_proactive(
    tenant_id: UUID,
    contact: Contact,
    message: ProactiveMessage,
    idem_key: str,
    event: InboundEvent | None,
    *,
    not_after: datetime | None = None,
) -> OutboundMessage | None:
    """A proactive message with the pack's idempotency key; None if that key was already
    used (a sweep seeing the same appointment again, or a retried event) and the message is
    still on its way or done. A message of that key that `expired`, or that failed with an
    `auth:` rejection (a revoked token, since fixed), is revived (and returned,
    to be queued again) while the new window is still open: after an outage, the sweep that
    offers the reminder again makes it go out."""
    now = timezone.now()
    expires_at = proactive_expiry(now, not_after)
    row = OutboundMessage(
        tenant_id=tenant_id,
        contact=contact,
        channel=contact.channel,
        idem_key=idem_key,
        kind=OutboundMessage.Kind.PROACTIVE,
        payload=dump_outbound(message),
        inbound_event=event,
        expires_at=expires_at,
        not_after=not_after,
    )
    OutboundMessage.objects.bulk_create([row], ignore_conflicts=True)
    if OutboundMessage.objects.filter(id=row.id).exists():
        return row
    if expires_at <= now:
        return None
    # Only `expired` and auth-failed rows come back: `discarded` is a person's decision
    # (ADR-031) and is never revived, nor are `sent`, `unknown` or other `failed` ones.
    revived = (
        OutboundMessage.objects.filter(
            tenant_id=tenant_id,
            idem_key=idem_key,
            kind=OutboundMessage.Kind.PROACTIVE,
            payload__isnull=False,
        )
        .filter(
            Q(status=Status.EXPIRED)
            | Q(status=Status.FAILED, last_error__startswith=AUTH_FAILURE_PREFIX)
        )
        .update(
            status=Status.PENDING,
            expires_at=expires_at,
            not_after=not_after,
            attempts=0,
            last_error="",
            unknown_at=None,
            payload=dump_outbound(message),
        )
    )
    if not revived:
        return None
    log.info("expired proactive message of tenant %s revived", tenant_id)
    return OutboundMessage.objects.select_related("contact").get(
        tenant_id=tenant_id, idem_key=idem_key
    )


def defer_sends(tenant_id: UUID, messages: list[OutboundMessage]) -> None:
    """Queue `send_message` for each message, in order: replies with the contact's `out:<h>`
    lock, proactive ones with `outp:<h>` (see `send_lock`). A contact's replies leave one at
    a time and in order; a reply and a reminder are not ordered between them.

    Must be called inside the same `tenant_tx` that saved `messages`: `enqueue` inserts the
    job through that same Django connection (never through the worker's own pool, see
    `autobot.runtime.queue`), so the job commits atomically with the message. A failure
    deferring it rolls the message back too, instead of leaving it saved with nothing to
    send it."""
    for message in messages:
        contact = message.contact
        if contact.channel == Channel.DEMO_WA:  # its delivery statuses are routed by this
            remember_demo_outbound(message.id, tenant_id)
        enqueue(
            SEND_MESSAGE,
            {"tenant_id": str(tenant_id), "outbound_id": str(message.id)},
            queue=OUTBOUND,
            lock=message_lock(tenant_id, message),
            priority=send_priority(message.kind),
        )


def send_priority(kind: str) -> int:
    return PROACTIVE_PRIORITY if kind == OutboundMessage.Kind.PROACTIVE else REPLY_PRIORITY


def message_lock(tenant_id: UUID, message: OutboundMessage) -> str:
    contact = message.contact
    return send_lock(
        tenant_id,
        contact.channel,
        contact.external_id,
        proactive=message.kind == OutboundMessage.Kind.PROACTIVE,
    )


# ── send_message ───────────────────────────────────────────────────

# Both `send_message` and `send_notification` retry by time (ADR-024), not by count.

DB_ERROR_RETRIES = 5  # database errors of send_message: bounded, unlike the provider's
BACKOFF_BASE_S = 5.0
BACKOFF_CAP_S = 300.0


def backoff_s(attempts: int) -> float:
    """Exponential wait with jitter, capped: 5 s, 10 s, 20 s… up to 300 s, each between half
    and all of that."""
    base = min(BACKOFF_CAP_S, BACKOFF_BASE_S * float(2 ** max(attempts - 1, 0)))
    return base * random.uniform(0.5, 1.0)  # noqa: S311


class SendRetry(Exception):
    """The provider asked to retry later: the job is retried, keeping its place
    before the contact's later messages (same lock, older job)."""

    def __init__(self, after_s: float | None) -> None:
        super().__init__(f"retry in {after_s} s" if after_s is not None else "retry")
        self.after_s = after_s


@contextual
def send_message(tenant_id: UUID, outbound_id: UUID) -> None:
    """Send one outbound message, never twice: the attempt is committed as `sending`
    before calling the provider, so a run cut in the middle is found as `sending` and
    left `unknown` instead of resent blindly.

    A transient failure (the provider says "later", or no connection was made) retries
    until `expires_at`, with no cap on attempts; past it the message is `expired`, not
    sent (ADR-024)."""
    tenant = tenant_by_id(tenant_id)
    if tenant is None:
        log.error("send_message of an unknown tenant %s: message left as it is", tenant_id)
        return

    breaker_open = False
    with tenant_tx(tenant.id):
        message = OutboundMessage.objects.select_for_update().filter(id=outbound_id).first()
        if message is not None:
            bind(
                tenant=tenant.slug,
                channel=message.channel,
                event_id=str(message.inbound_event_id or ""),
            )
        if message is None:
            # Enqueued atomically with the row, so this should never happen: if it does,
            # the job has nothing to send and ops_check will see the stuck state.
            log.error("send_message: outbound %s of tenant %s not found", outbound_id, tenant.id)
            return
        if message.status in (
            Status.SENT,
            Status.UNKNOWN,
            Status.FAILED,
            Status.EXPIRED,
            Status.DISCARDED,
        ):
            return  # done, or never resent blindly
        if message.status == Status.SENDING:
            message.status = Status.UNKNOWN
            message.unknown_at = timezone.now()
            message.last_error = "interrupted while sending"
            message.save(update_fields=["status", "last_error", "unknown_at"])
            log.warning("message %s was cut while sending: left unknown", message.id)
            return
        contact = message.contact
        now = timezone.now()
        if message.expires_at is not None and now >= message.expires_at:
            _expire(tenant.id, message, now)
            return
        if message.payload is None:
            message.status, message.last_error = Status.FAILED, "other: payload expired"
            message.save(update_fields=["status", "last_error", "unknown_at"])
            return
        # Everything that may fail before the call happens while still `pending`: an error
        # here rolls back and leaves the message as it was (the job fails, ops sees it).
        ep = endpoint(tenant, message.channel)
        provider = ep.adapter.type
        rendered = ep.adapter.render(load_outbound(message.payload), ep.channel)
        if ep.secrets is not None and BREAKER.is_open(provider):
            breaker_open = True
        else:
            message.status = Status.SENDING
            message.attempts += 1
            message.save(update_fields=["status", "attempts"])

    if breaker_open:
        wait = _wait_for_provider(provider, ep, message.kind)
        if message.expires_at is not None:  # never past the expiry, like `_record`
            wait = min(wait, max((message.expires_at - timezone.now()).total_seconds(), 1.0))
        raise SendRetry(wait)

    # No transaction while the provider answers.
    if ep.secrets is None:
        outcome: SendOutcome = Rejected("main channel disabled", "other")
    else:
        outcome = ep.adapter.send(rendered, _recipient(contact), ep.channel, ep.secrets, message.id)
        _observe(provider, tenant.id, outcome)

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


def _observe(provider: str, tenant_id: UUID, outcome: SendOutcome) -> None:
    """Feed the provider breaker: a transport failure counts against it; any answer of the
    provider (sent, refused, asked to slow down) proves it is up. An auth refusal or an
    unreadable answer says nothing."""
    match outcome:
        case RetryLater(kind="server" | "network") | Ambiguous(transport=True):
            BREAKER.record_failure(provider, tenant_id)
        case Sent() | RetryLater() | Rejected(kind="recipient" | "other"):
            BREAKER.record_success(provider)


def _wait_for_provider(provider: str, ep: Endpoint, kind: str = "reply") -> float:
    """The breaker is open: this message is not sent. If a probe is due, whoever claims
    it runs it (no transaction open), and a success closes the breaker. Returns how long
    the message waits before trying again: until the next probe plus a jitter that depends
    on its kind (see `REPLY_WAIT_SPREAD_S`)."""
    if BREAKER.claim_probe(provider):
        ok = ep.adapter.probe(ep.channel, ep.secrets)
        BREAKER.probe_result(provider, ok)
        if ok:
            return 1.0
    wait: float = BREAKER.seconds_to_probe(provider)
    low, high = (
        PROACTIVE_WAIT_SPREAD_S if kind == OutboundMessage.Kind.PROACTIVE else REPLY_WAIT_SPREAD_S
    )
    return min(max(wait, 5.0), PROBE_WAIT_MAX_S) + random.uniform(low, high)  # noqa: S311


def _expire(tenant_id: UUID, message: OutboundMessage, now: datetime) -> None:
    """Past `expires_at`: not sent. A reply is replaced by one apology (see
    `_apologize`); a reminder simply lapses."""
    message.status = Status.EXPIRED
    message.last_error = "expired before it could be delivered"
    message.save(update_fields=["status", "last_error", "unknown_at"])
    log.warning("outbound %s expired (%s) without being sent", message.id, message.kind)
    if message.kind == OutboundMessage.Kind.REPLY and not message.idem_key.startswith(
        APOLOGY_PREFIX
    ):
        _apologize(tenant_id, message, now)


def _apologize(tenant_id: UUID, expired: OutboundMessage, now: datetime) -> None:
    """One short apology instead of the stale reply: at most one per contact every
    `APOLOGY_EVERY`, idempotent by `apology:<expired message id>`. Runs under the contact's
    `out:<h>` lock, so two expired replies never both see "none sent yet"."""
    contact = expired.contact
    if contact.unreachable:
        return
    if OutboundMessage.objects.filter(
        contact_id=contact.id,
        idem_key__startswith=APOLOGY_PREFIX,
        created_at__gt=now - APOLOGY_EVERY,
    ).exists():
        return
    event = expired.inbound_event
    row = OutboundMessage(
        tenant_id=tenant_id,
        contact=contact,
        channel=expired.channel,
        idem_key=f"{APOLOGY_PREFIX}{expired.id}",
        kind=OutboundMessage.Kind.REPLY,
        payload=dump_outbound(Text(APOLOGY_TEXT)),
        inbound_event=event,
        expires_at=now + APOLOGY_TTL,
    )
    OutboundMessage.objects.bulk_create([row], ignore_conflicts=True)
    if OutboundMessage.objects.filter(id=row.id).exists():
        defer_sends(tenant_id, [row])


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
            # A send got through: the contact is not unreachable any more.
            Contact.objects.filter(id=message.contact_id, unreachable=True).update(
                unreachable=False
            )
        case Rejected():
            message.status = Status.FAILED
            message.last_error = f"{outcome.kind}: {outcome.reason}"
            if outcome.kind == "recipient":
                Contact.objects.filter(id=message.contact_id).update(unreachable=True)
            elif outcome.kind == "auth":
                # The 🔴 alert is sent by ops_check, which looks for these.
                log.error("ALERT tenant %s: channel token rejected (%s)", slug, outcome.reason)
        case RetryLater():
            # No cap on attempts: it is retried until `expires_at` (checked at the start of
            # the next run). The wait is the provider's `retry_after`, else a backoff, and
            # never goes past the expiry.
            message.status = Status.PENDING
            message.last_error = f"retry later ({outcome.kind})"
            message.save(update_fields=fields)
            wait = outcome.after_s if outcome.after_s is not None else backoff_s(message.attempts)
            if message.expires_at is not None:
                remaining = (message.expires_at - timezone.now()).total_seconds()
                wait = min(wait, max(remaining, 1.0))
            return SendRetry(wait)
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
