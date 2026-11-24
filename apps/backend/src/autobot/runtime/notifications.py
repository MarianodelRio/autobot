"""Owner notices and operation alerts."""

import hashlib
import logging
import random
import secrets as random_secrets
from datetime import timedelta
from uuid import UUID, uuid4

from django.conf import settings
from django.core.cache import cache
from django.db import connection, transaction
from django.db.models import F
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
from autobot.tenancy.registry import get_registry
from autobot.tenancy.schema import TelegramSecrets
from autobot.tenancy.tx import tenant_tx
from core.replies import Text
from core.serialization import Outbound

log = logging.getLogger(__name__)
COOLDOWN_S = 30 * 60
# An owner notice older than this is stale (a booking notice two hours late no longer
# helps): it becomes `expired`, with no apology.
NOTICE_TTL = timedelta(hours=2)
# The notify bot's limits at Telegram: ~30 messages/s per bot, ~1/s per chat. We stay
# under: 25/s overall and one per owner chat per second. Per process: see runtime/ratelimit.py.
LIMITER = SlotLimiter(rate_per_s=25.0, key_interval_s=1.0)
# Alerts that only a person resolves from the panel; every other kind self-resolves
# once ops/check.py stops finding it.
MANUAL_KINDS = frozenset({"deploy_aborted", "deploy_rollback"})
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
    tenant = get_registry().by_id.get(tenant_id)
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


def _cooldown_key(kind: str, tenant_id: UUID | None) -> str:
    return f"ops:{_alert_digest(kind, tenant_id).hex()}"


# `OpsAlert.last_delivery` values of an alert that never reached the operator.
UNDELIVERED = ("failed", "unconfigured")


def send_ops_alert(
    kind: str, tenant_id: UUID | None, text: str, *, informational: bool = False
) -> bool:
    """Persist the alert, reserve a 30-minute cooldown, then send outside the transaction.

    `informational` (e.g. "deployed fine") skips the cooldown and is saved already
    resolved: it is a one-off notice, never an ongoing problem to track.
    A failed/ambiguous send also keeps the cooldown to prevent an alert storm.
    """
    digest = _alert_digest(kind, tenant_id)
    key = _cooldown_key(kind, tenant_id)
    now = timezone.now()
    # DatabaseCache.add alone can race when replacing an expired entry.
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT pg_advisory_xact_lock(%s)", [int.from_bytes(digest[:8], signed=True)]
            )
        if informational:
            alert = OpsAlert.objects.create(
                kind=kind,
                tenant_id=tenant_id,
                severity=_severity(text),
                text=text,
                first_seen_at=now,
                last_seen_at=now,
                auto_resolves=kind not in MANUAL_KINDS,
                resolved_at=now,
                resolved_by="info",
            )
            send = True
        else:
            existing = (
                OpsAlert.objects.select_for_update()
                .filter(kind=kind, tenant_id=tenant_id, resolved_at__isnull=True)
                .first()
            )
            if existing is None:
                alert = OpsAlert.objects.create(
                    kind=kind,
                    tenant_id=tenant_id,
                    severity=_severity(text),
                    text=text,
                    first_seen_at=now,
                    last_seen_at=now,
                    auto_resolves=kind not in MANUAL_KINDS,
                )
            else:
                OpsAlert.objects.filter(id=existing.id).update(
                    occurrences=F("occurrences") + 1, last_seen_at=now, text=text
                )
                alert = existing
            send = cache.add(key, True, timeout=COOLDOWN_S)
        if not send:
            # A delivery that failed (or had nowhere to go) stays visible while the
            # cooldown lasts: ops_check withholds its heartbeat on it.
            OpsAlert.objects.filter(id=alert.id).exclude(last_delivery__in=UNDELIVERED).update(
                last_delivery="cooldown"
            )
            return False
    if not settings.OPS_TELEGRAM_CHAT_ID or bot_secrets() is None:
        log.warning("ops alert %s only logged: recipient or bot unconfigured", kind)
        delivery, sent = "unconfigured", False
    else:
        outcome = deliver(Text(text), str(settings.OPS_TELEGRAM_CHAT_ID), uuid4())
        sent = isinstance(outcome, Sent)
        delivery = "sent" if sent else "failed"
    OpsAlert.objects.filter(id=alert.id).update(
        last_delivery=delivery, sent_count=F("sent_count") + 1, last_sent_at=now
    )
    return sent


def resolve_alert(alert: OpsAlert, *, by: str, notify: bool = False) -> None:
    """Resolve and clear the cooldown, so a problem that returns is reported at once.

    `notify`: also tell the ops chat it is over (closes the loop on "stopping the worker
    raises the alert and starting it again recovers it"). Used only for alerts that
    resolved themselves, and only the critical ones, to avoid a message for every
    minor flap; a person who resolves one from the panel already knows it is done.
    """
    OpsAlert.objects.using(alert._state.db or "default").filter(id=alert.id).update(
        resolved_at=timezone.now(), resolved_by=by
    )
    cache.delete(_cooldown_key(alert.kind, alert.tenant_id))
    if notify and settings.OPS_TELEGRAM_CHAT_ID and bot_secrets() is not None:
        deliver(Text(f"✅ Resuelta: {alert.text}"), str(settings.OPS_TELEGRAM_CHAT_ID), uuid4())
