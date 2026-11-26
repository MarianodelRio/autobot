"""Owner notices and operation alerts."""

import hashlib
import logging
import random
import secrets as random_secrets
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from django.conf import settings
from django.db import connection, transaction
from django.db.models import F, Max, Q
from django.utils import timezone
from pydantic import SecretStr

from autobot.channels.adapters import TELEGRAM
from autobot.channels.base import RetryLater, SendOutcome, Sent
from autobot.ops.logging import bind, contextual
from autobot.ops.models import OpsAlert
from autobot.owner import links
from autobot.runtime.cache import record_auth_outcome
from autobot.runtime.jobs import OUTBOUND, SEND_NOTIFICATION
from autobot.runtime.models import Notification
from autobot.runtime.outbound import SendRetry, backoff_s
from autobot.runtime.queue import enqueue
from autobot.runtime.ratelimit import SlotLimiter
from autobot.runtime.summary import OWNER_SUMMARY_KIND
from autobot.tenancy.registry import tenant_by_id
from autobot.tenancy.schema import TelegramSecrets
from autobot.tenancy.tx import tenant_tx
from core.replies import Text
from core.serialization import Outbound

log = logging.getLogger(__name__)
# An owner notice older than this is stale (a booking notice two hours late no longer
# helps): it becomes `expired`, with no apology.
NOTICE_TTL = timedelta(hours=2)
# The notify bot's limits at Telegram: ~30 messages/s per bot, ~1/s per chat. We stay
# under: 25/s overall and one per owner chat per second. Per process: see runtime/ratelimit.py.
LIMITER = SlotLimiter(rate_per_s=25.0, key_interval_s=1.0)
_SEVERITY_BY_EMOJI = {"🔴": "critical", "🟠": "warning", "🟡": "notice", "🟢": "info"}


def bot_secrets() -> TelegramSecrets | None:
    if not settings.NOTIFY_BOT_TOKEN:
        return None
    # A random secret when unset makes the webhook's signature check always fail
    # (settings.py requires 32+ characters when it IS set), like the demo door.
    webhook_secret = settings.NOTIFY_BOT_WEBHOOK_SECRET or random_secrets.token_urlsafe(32)
    return TelegramSecrets(
        bot_token=SecretStr(settings.NOTIFY_BOT_TOKEN), webhook_secret=SecretStr(webhook_secret)
    )


def deliver(reply: Outbound, chat_id: str, reference: UUID) -> SendOutcome | None:
    secrets = bot_secrets()
    if secrets is None:
        return None
    outcome = TELEGRAM.send(TELEGRAM.render(reply, None), chat_id, None, secrets, reference)
    record_auth_outcome("notify", outcome)
    return outcome


@contextual
def send_notification(tenant_id: UUID, notification_id: UUID, *, attempts: int = 0) -> None:
    """Deliver one owner notice, never twice. It retries by time (ADR-024), not by count:
    a 429 or a refusal to connect is retried (the provider's `retry_after`, else a capped
    backoff with jitter), and a notice older than `NOTICE_TTL` is `expired`, not sent. A
    5xx or a timeout is ambiguous: the notice stays `failed`, never resent blindly.

    Before calling Telegram, `LIMITER` must grant a slot (global rate and one per owner
    chat); without one the notice stays `pending` and the job is deferred."""
    tenant = tenant_by_id(tenant_id)
    if tenant is None:
        log.error("notification of unknown tenant %s", tenant_id)
        return
    with tenant_tx(tenant_id):
        row = Notification.objects.select_for_update().filter(id=notification_id).first()
        bind(tenant=tenant.slug, channel="notification", event_id="")
        if row is None:
            # Enqueued atomically with the row (see runtime/queue.py): never expected.
            log.error(
                "send_notification: notification %s of tenant %s not found",
                notification_id,
                tenant_id,
            )
            return
        if row.status != Notification.Status.PENDING:
            return
        if timezone.now() >= row.created_at + NOTICE_TTL:
            row.status = Notification.Status.EXPIRED
            row.save(update_fields=["status"])
            log.warning("notification %s expired without being sent", row.id)
            return
        owner = tenant.document.owner
        # owner.notify only gates per-event notices; the summary has its own toggle
        # (owner.summary_monthly), already checked when send_owner_summary created this
        # row.
        allowed = (row.kind == OWNER_SUMMARY_KIND or row.kind in owner.notify) if owner else False
        chat = links.owner_chat(tenant_id) if allowed else None
        if allowed and chat is None and bot_secrets() is not None:
            # The owner has not linked a chat (yet): keep the notice; `release_held` queues
            # it when they do (ADR-026).
            row.status = Notification.Status.HELD
            row.save(update_fields=["status"])
            log.info("notification %s held: the owner has no chat linked", notification_id)
            return
        if chat is None or bot_secrets() is None:
            row.status = Notification.Status.FAILED
            row.save(update_fields=["status"])
            log.info("notification %s only logged: recipient or bot unconfigured", notification_id)
            return
    # No transaction while waiting for a slot or while Telegram answers.
    wait = LIMITER.acquire(str(chat))
    if wait is not None:
        raise SendRetry(wait + random.uniform(0.0, 1.0))  # noqa: S311 (spreads the retries)
    with tenant_tx(tenant_id):
        row = Notification.objects.select_for_update().get(id=notification_id)
        if row.status != Notification.Status.PENDING:
            return
        # Claim durably before network I/O. A crash or ambiguous result stays failed:
        # notification has no unknown state, and must never be resent blindly.
        row.status = Notification.Status.FAILED
        row.save(update_fields=["status"])
    outcome = deliver(Text(row.text), str(chat), row.id)
    retry = isinstance(outcome, RetryLater)
    with tenant_tx(tenant_id):
        if isinstance(outcome, Sent):
            Notification.objects.filter(id=row.id).update(
                status=Notification.Status.SENT, sent_at=timezone.now()
            )
        elif retry:
            Notification.objects.filter(id=row.id).update(status=Notification.Status.PENDING)
    if isinstance(outcome, RetryLater):
        wait_s = outcome.after_s if outcome.after_s is not None else backoff_s(attempts)
        remaining = (row.created_at + NOTICE_TTL - timezone.now()).total_seconds()
        raise SendRetry(min(wait_s, max(remaining, 1.0)))
    if not isinstance(outcome, Sent):
        log.warning("notification %s failed (%s)", row.id, type(outcome).__name__)


def release_held(tenant_id: UUID) -> int:
    """The owner just linked a chat: queue the notices held for it that are still younger
    than `NOTICE_TTL` and expire the older ones. Returns how many were queued. Idempotent:
    only `held` rows change, and each gets one job."""
    now = timezone.now()
    queued = 0
    with tenant_tx(tenant_id):
        rows = list(
            Notification.objects.select_for_update()
            .filter(status=Notification.Status.HELD)
            .order_by("created_at")[:500]
        )
        for row in rows:
            if now >= row.created_at + NOTICE_TTL:
                row.status = Notification.Status.EXPIRED
                row.save(update_fields=["status"])
                continue
            row.status = Notification.Status.PENDING
            row.save(update_fields=["status"])
            enqueue(
                SEND_NOTIFICATION,
                {"tenant_id": str(tenant_id), "notification_id": str(row.id)},
                queue=OUTBOUND,
                lock=f"owner:{tenant_id}",
            )
            queued += 1
    return queued


def _severity(text: str) -> str:
    for char in text:
        if char in _SEVERITY_BY_EMOJI:
            return _SEVERITY_BY_EMOJI[char]
    return "warning"


def _alert_digest(kind: str, tenant_id: UUID | None) -> bytes:
    return hashlib.sha256(f"{kind}:{tenant_id}".encode()).digest()


# `OpsAlert.last_delivery`: `sent`; `failed` and `unconfigured` never reached the
# operator (ops_check retries them hourly and withholds its heartbeat on a critical one);
# `panel` is a 🟡 one, never pushed; `throttled`, a reopened event already pushed within
# the hour; `cooldown` only in rows from before ADR-031.
UNDELIVERED = ("failed", "unconfigured")
# A reopened event is pushed at most once per hour per (kind, tenant), and an undelivered
# push is retried at most once per hour (ADR-031).
REPUSH_EVERY = timedelta(hours=1)


def send_ops_alert(
    kind: str,
    tenant_id: UUID | None,
    text: str,
    *,
    informational: bool = False,
    case_count: int | None = None,
    last_case_at: datetime | None = None,
    details: dict[str, Any] | None = None,
) -> bool:
    """Open or update the incident of (kind, tenant) and, when it deserves it, push it to
    the ops chat outside the transaction. True when a push went out.

    Pushed (ADR-031): a 🔴 or 🟠 incident when it opens, an escalation of an open one to
    🔴/🟠, and a reopened event (a new period after a review) at most once per hour. A 🟡
    one is never pushed (`panel`): it is in the panel and the daily summary. An incident
    that stays open is not pushed again. `informational` (e.g. "deployed fine") is saved
    already resolved and always pushed.

    `case_count`/`last_case_at`/`details`: as ops_check computed them; an event that
    carries no count (a deploy one) counts each call as one more case."""
    from autobot.ops.incidents import PUSHED, SEVERITY_RANK, kind_info

    digest = _alert_digest(kind, tenant_id)
    now = timezone.now()
    severity = _severity(text)
    info = kind_info(kind)
    event = info.nature == "event"
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT pg_advisory_xact_lock(%s)", [int.from_bytes(digest[:8], signed=True)]
            )
        if informational or info.informational:
            alert = OpsAlert.objects.create(
                kind=kind,
                tenant_id=tenant_id,
                severity=severity,
                text=text,
                first_seen_at=now,
                last_seen_at=now,
                auto_resolves=not event,
                resolved_at=now,
                resolved_by="info",
                details=details or {},
            )
            push = True
        else:
            existing = (
                OpsAlert.objects.select_for_update()
                .filter(kind=kind, tenant_id=tenant_id, resolved_at__isnull=True)
                .first()
            )
            if existing is None:
                alert, push = _open(
                    kind,
                    tenant_id,
                    text,
                    severity,
                    event,
                    now,
                    case_count=case_count,
                    last_case_at=last_case_at,
                    details=details,
                )
            else:
                alert = existing
                changes: dict[str, Any] = {
                    "occurrences": F("occurrences") + 1,
                    "last_seen_at": now,
                    "text": text,
                    "severity": severity,
                    # A row from before its kind became an event (ADR-031) turns into one.
                    "auto_resolves": not event,
                }
                if case_count is not None:
                    changes["case_count"] = case_count
                elif event:
                    changes["case_count"] = F("case_count") + 1
                if last_case_at is not None or (event and case_count is None):
                    changes["last_case_at"] = last_case_at or now
                if details is not None:
                    changes["details"] = details
                OpsAlert.objects.filter(id=existing.id).update(**changes)
                # Severity goes both ways; only an escalation to 🔴/🟠 is pushed.
                push = severity in PUSHED and SEVERITY_RANK[severity] > SEVERITY_RANK.get(
                    existing.severity, 0
                )
        if not push:
            return False
    return _push(alert.id, text, now)


def _open(
    kind: str,
    tenant_id: UUID | None,
    text: str,
    severity: str,
    event: bool,
    now: datetime,
    *,
    case_count: int | None,
    last_case_at: datetime | None,
    details: dict[str, Any] | None,
) -> tuple[OpsAlert, bool]:
    """A new open period of (kind, tenant): an event inherits the latest watermark. True
    when it must be pushed."""
    from autobot.ops.incidents import PLATFORM_CLOSINGS, PUSHED, inherited_watermark

    previous = OpsAlert.objects.filter(kind=kind, tenant_id=tenant_id)
    reopened = (
        event
        and previous.filter(resolved_at__isnull=False)
        .exclude(resolved_by__in=PLATFORM_CLOSINGS)
        .exclude(resolved_by="")
        .exists()
    )
    delivery = ""
    if severity not in PUSHED:
        delivery = "panel"
    elif reopened:
        last_push = previous.aggregate(at=Max("last_sent_at"))["at"]
        if last_push is not None and now - last_push < REPUSH_EVERY:
            delivery = "throttled"
    alert = OpsAlert.objects.create(
        kind=kind,
        tenant_id=tenant_id,
        severity=severity,
        text=text,
        first_seen_at=now,
        last_seen_at=now,
        auto_resolves=not event,
        review_watermark=inherited_watermark(kind, tenant_id, now) if event else None,
        case_count=case_count if case_count is not None else (1 if event else 0),
        last_case_at=last_case_at or (now if event else None),
        details=details or {},
        last_delivery=delivery,
    )
    return alert, delivery == ""


def _push(alert_id: UUID, text: str, now: datetime) -> bool:
    """Deliver an incident's text to the ops chat; never inside a transaction."""
    if not settings.OPS_TELEGRAM_CHAT_ID or bot_secrets() is None:
        log.warning("ops alert only logged: recipient or bot unconfigured")
        delivery, sent = "unconfigured", False
    else:
        outcome = deliver(Text(text), str(settings.OPS_TELEGRAM_CHAT_ID), uuid4())
        sent = isinstance(outcome, Sent)
        delivery = "sent" if sent else "failed"
    OpsAlert.objects.filter(id=alert_id).update(
        last_delivery=delivery, sent_count=F("sent_count") + 1, last_sent_at=now
    )
    return sent


def retry_undelivered(now: datetime | None = None) -> int:
    """Push again, at most once per hour, the open 🔴/🟠 incidents whose push never
    reached the operator (Telegram down, revoked token): not a new notice, the same one.
    Once Telegram answers again, `last_delivery` becomes `sent` and ops_check stops
    withholding its heartbeat (`/fail`). Returns how many went out."""
    from autobot.ops.incidents import PUSHED

    now = now or timezone.now()
    due = OpsAlert.objects.filter(
        Q(last_sent_at__isnull=True) | Q(last_sent_at__lte=now - REPUSH_EVERY),
        resolved_at__isnull=True,
        severity__in=PUSHED,
        last_delivery__in=UNDELIVERED,
    )
    sent = 0
    for alert in due:
        # Claimed first: a concurrent pass (never expected) does not push it twice.
        claimed = OpsAlert.objects.filter(
            id=alert.id, last_sent_at=alert.last_sent_at, last_delivery__in=UNDELIVERED
        ).update(last_sent_at=now)
        if claimed and _push(alert.id, alert.text, now):
            sent += 1
    return sent


def resolve_alert(alert: OpsAlert, *, by: str, notify: bool = False) -> None:
    """Close an incident: `auto` (the condition is gone) or `outage` (explained by a
    provider-wide outage with its own incident). A review closes an event through
    `ops.incidents.review` instead.

    `notify`: also tell the ops chat it is over (closes the loop on "stopping the worker
    raises the alert and starting it again recovers it"). Used only for conditions that
    resolved themselves, and only the critical ones, to avoid a message for every
    minor flap.
    """
    OpsAlert.objects.using(alert._state.db or "default").filter(id=alert.id).update(
        resolved_at=timezone.now(), resolved_by=by
    )
    if notify and settings.OPS_TELEGRAM_CHAT_ID and bot_secrets() is not None:
        deliver(Text(f"✅ Resuelta: {alert.text}"), str(settings.OPS_TELEGRAM_CHAT_ID), uuid4())
