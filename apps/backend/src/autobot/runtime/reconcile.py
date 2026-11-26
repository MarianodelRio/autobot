"""Reconciling ambiguous sends (ADR-026).

A send whose outcome is unknown (a Meta 5xx without a body, any Telegram 5xx, a timeout, a
worker killed in the middle) is left `unknown`. The first evidence comes from the
provider: a Meta delivery status turns it `sent` (`runtime/process.py`). Telegram has no
delivery status, and a status can also never come. So, periodically and per tenant:

- an `unknown` message older than `RECONCILE_WAIT` with no evidence of delivery (no
  provider id) is resent ONCE (`ambiguous_resends` 0 -> 1), through the normal send path
  (`send_message`: the contact's lock, the breaker, `expires_at`), and only if its class
  declares that a duplicate is harmless (`dup_policy`);
- one past its `expires_at` is not resent: it is marked `expired`;
- if the resend is ambiguous again it stays `unknown` for a person.

Held owner notices (`Notification.Status.HELD`) that went stale are expired here too.
Only ids are used and logged.
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from django.utils import timezone

from autobot.channels.demo.doors import door
from autobot.runtime.jobs import OUTBOUND, SEND_MESSAGE
from autobot.runtime.models import DEMO_CHANNELS, Channel, Notification, OutboundMessage
from autobot.runtime.outbound import (
    MAX_AMBIGUOUS_RESENDS,
    RECONCILE_WAIT,
    SAFE_DUP_KINDS,
    message_lock,
    send_priority,
)
from autobot.runtime.queue import enqueue
from autobot.tenancy.registry import LoadedTenant, get_registry
from autobot.tenancy.tx import tenant_tx

log = logging.getLogger(__name__)

BATCH = 100  # per tenant and tick: a bounded amount of work
Status = OutboundMessage.Status


@dataclass(frozen=True)
class ReconcileResult:
    resent: int = 0
    expired: int = 0
    held_expired: int = 0


def can_deliver(tenant: LoadedTenant, channel: str) -> bool:
    """Whether a send on `channel` would reach a provider (else it would only fail)."""
    if tenant.ambiguous or tenant.document.status == "offboarded":
        return False
    if channel == Channel.MAIN:
        return tenant.main_enabled
    return channel in DEMO_CHANNELS and door(Channel(channel)) is not None


def reconcile_tenant(tenant: LoadedTenant, now: datetime | None = None) -> ReconcileResult:
    now = now or timezone.now()
    resent = expired = 0
    with tenant_tx(tenant.id):
        # Served by `outbound_unknown_idx` (tenant, unknown_at) WHERE status = 'unknown'.
        rows = list(
            OutboundMessage.objects.select_for_update(skip_locked=True)
            .select_related("contact")
            .filter(
                status=Status.UNKNOWN,
                unknown_at__lt=now - RECONCILE_WAIT,
                ambiguous_resends__lt=MAX_AMBIGUOUS_RESENDS,
                kind__in=SAFE_DUP_KINDS,
                provider_message_id__isnull=True,  # an id is evidence it was accepted
            )
            .order_by("unknown_at")[:BATCH]
        )
        for message in rows:
            if message.expires_at is not None and now >= message.expires_at:
                message.status = Status.EXPIRED
                message.unknown_at = None
                message.last_error = "expired while ambiguous"
                message.save(update_fields=["status", "unknown_at", "last_error"])
                expired += 1
                continue
            if message.payload is None or not can_deliver(tenant, message.channel):
                continue  # nothing to send, or nowhere to send it: a person looks
            message.status = Status.PENDING
            message.unknown_at = None
            message.ambiguous_resends += 1
            message.last_error = "resent after an ambiguous send"
            message.save(update_fields=["status", "unknown_at", "ambiguous_resends", "last_error"])
            enqueue(
                SEND_MESSAGE,
                {"tenant_id": str(tenant.id), "outbound_id": str(message.id)},
                queue=OUTBOUND,
                lock=message_lock(tenant.id, message),
                priority=send_priority(message.kind),
            )
            resent += 1
    if resent or expired:
        log.warning(
            "tenant %s: %s ambiguous sends resent once, %s expired", tenant.slug, resent, expired
        )
    return ReconcileResult(resent, expired)


def expire_held(tenant_id: UUID, now: datetime | None = None) -> int:
    """Held owner notices older than `NOTICE_TTL` are stale: `expired`."""
    from autobot.runtime.notifications import NOTICE_TTL

    now = now or timezone.now()
    with tenant_tx(tenant_id):
        return Notification.objects.filter(
            status=Notification.Status.HELD, created_at__lt=now - NOTICE_TTL
        ).update(status=Notification.Status.EXPIRED, failed_at=now)


def reconcile_all(now: datetime | None = None) -> ReconcileResult:
    """Every tenant; one failing never stops the others."""
    now = now or timezone.now()
    resent = expired = held = 0
    for tenant in get_registry().tenants:
        if tenant.ambiguous or tenant.document.status == "offboarded":
            continue
        try:
            result = reconcile_tenant(tenant, now)
            held += expire_held(tenant.id, now)
        except Exception:
            log.exception("reconcile of tenant %s failed", tenant.slug)
            continue
        resent += result.resent
        expired += result.expired
    return ReconcileResult(resent, expired, held)
