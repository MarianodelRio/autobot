"""Owner notices and operation alerts."""

import hashlib
import logging
import secrets as random_secrets
from uuid import UUID, uuid4

from django.conf import settings
from django.core.cache import cache
from django.db import connection, transaction
from django.db.models import F
from django.utils import timezone
from pydantic import SecretStr

from autobot.channels.adapters import TELEGRAM
from autobot.channels.base import Rejected, RetryLater, SendOutcome, Sent
from autobot.ops.logging import bind, contextual
from autobot.ops.models import OpsAlert
from autobot.owner import links
from autobot.runtime.models import Notification
from autobot.runtime.outbound import SendRetry
from autobot.runtime.summary import OWNER_SUMMARY_KIND
from autobot.tenancy.registry import get_registry
from autobot.tenancy.schema import TelegramSecrets
from autobot.tenancy.tx import tenant_tx
from core.replies import Text
from core.serialization import Outbound

log = logging.getLogger(__name__)
COOLDOWN_S = 30 * 60
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
    if isinstance(outcome, Rejected) and outcome.kind == "auth":
        cache.set("bot:notify:auth", True, timeout=None)
    elif isinstance(outcome, Sent):
        cache.delete("bot:notify:auth")
    return outcome


@contextual
def send_notification(
    tenant_id: UUID, notification_id: UUID, *, last_attempt: bool = False
) -> None:
    tenant = get_registry().by_id.get(tenant_id)
    if tenant is None:
        log.error("notification of unknown tenant %s", tenant_id)
        return
    with tenant_tx(tenant_id):
        row = Notification.objects.select_for_update().filter(id=notification_id).first()
        bind(tenant=tenant.slug, channel="notification", event_id="")
        if row is None or row.status != Notification.Status.PENDING:
            return
        owner = tenant.document.owner
        # owner.notify only gates per-event notices; the summary has its own toggle
        # (owner.summary_monthly), already checked when send_owner_summary created this
        # row.
        allowed = row.kind == OWNER_SUMMARY_KIND or row.kind in owner.notify if owner else False
        chat = links.owner_chat(tenant_id) if allowed else None
        # Claim durably before network I/O. A crash or ambiguous result stays failed:
        # notification has no unknown state, and must never be resent blindly.
        row.status = Notification.Status.FAILED
        row.save(update_fields=["status"])
    if chat is None or bot_secrets() is None:
        log.info("notification %s only logged: recipient or bot unconfigured", notification_id)
        return
    outcome = deliver(Text(row.text), str(chat), row.id)
    retry = isinstance(outcome, RetryLater) and not last_attempt
    with tenant_tx(tenant_id):
        if isinstance(outcome, Sent):
            Notification.objects.filter(id=row.id).update(
                status=Notification.Status.SENT, sent_at=timezone.now()
            )
        elif retry:
            Notification.objects.filter(id=row.id).update(status=Notification.Status.PENDING)
    if retry:
        assert isinstance(outcome, RetryLater)
        raise SendRetry(outcome.after_s)
    if not isinstance(outcome, Sent):
        log.warning("notification %s failed (%s)", row.id, type(outcome).__name__)


def _severity(text: str) -> str:
    for char in text:
        if char in _SEVERITY_BY_EMOJI:
            return _SEVERITY_BY_EMOJI[char]
    return "warning"


def _cooldown_key(kind: str, tenant_id: UUID | None) -> str:
    digest = hashlib.sha256(f"{kind}:{tenant_id}".encode()).digest()
    return f"ops:{digest.hex()}"


def send_ops_alert(
    kind: str, tenant_id: UUID | None, text: str, *, informational: bool = False
) -> bool:
    """Persist the alert, reserve a 30-minute cooldown, then send outside the transaction.

    `informational` (e.g. "deployed fine") skips the cooldown and is saved already
    resolved: it is a one-off notice, never an ongoing problem to track.
    A failed/ambiguous send also keeps the cooldown to prevent an alert storm.
    """
    digest = hashlib.sha256(f"{kind}:{tenant_id}".encode()).digest()
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
            OpsAlert.objects.filter(id=alert.id).update(last_delivery="cooldown")
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


def resolve_alert(alert: OpsAlert, *, by: str) -> None:
    """Resolve and clear the cooldown, so a problem that returns is reported at once."""
    OpsAlert.objects.using(alert._state.db or "default").filter(id=alert.id).update(
        resolved_at=timezone.now(), resolved_by=by
    )
    cache.delete(_cooldown_key(alert.kind, alert.tenant_id))
