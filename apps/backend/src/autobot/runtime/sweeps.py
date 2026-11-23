"""Safety-net sweeps run by `ops_check`: work that got stuck without anybody noticing.

Jobs are enqueued atomically with their rows (`runtime/queue.py`), so these should find
nothing; they exist for the day a worker dies in a bad spot or a job is lost. Only ids
are used and logged, never personal data.

- outbound `sending` with no live job: a run cut while talking to the provider; the
  outcome is unknown, so it becomes `unknown` (never resent blindly, ops resolves it).
- outbound `pending` older than 10 minutes with no live job: `send_message` is
  idempotent by the message state, so it is queued again.
- inbound_event `pending` older than 5 minutes with no live job: reported to ops and,
  when recent, queued again. `process_event`/`apply_status` are idempotent by the event
  status (tx2 does nothing if it is no longer `pending`) and replies are created only
  there. The re-queue window (1 hour) bounds a poison event that would fail forever: past
  it, a person decides.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from django.db import connection
from django.utils import timezone

from autobot.channels.adapters import endpoint
from autobot.channels.base import InboundItem, parse_stored
from autobot.runtime.jobs import (
    APPLY_STATUS,
    INBOUND,
    OUTBOUND,
    PROCESS_EVENT,
    SEND_MESSAGE,
    process_event_queue,
)
from autobot.runtime.locks import conversation_lock
from autobot.runtime.models import InboundEvent, OutboundMessage
from autobot.runtime.outbound import message_lock, send_priority
from autobot.runtime.queue import enqueue
from autobot.tenancy.registry import LoadedTenant
from autobot.tenancy.tx import tenant_tx

log = logging.getLogger(__name__)

OUTBOUND_STUCK_AFTER = timedelta(minutes=10)
OUTBOUND_REQUEUE_WINDOW = timedelta(hours=24)
INBOUND_STUCK_AFTER = timedelta(minutes=5)
INBOUND_REQUEUE_WINDOW = timedelta(hours=1)

MAX_PER_SWEEP = 200  # a bounded amount of work per tick


@dataclass(frozen=True)
class SweepResult:
    outbound_unknown: int = 0
    outbound_requeued: int = 0
    outbound_stuck: int = 0  # pending with no live job and not requeued (too old)
    inbound_requeued: int = 0
    inbound_stuck: int = 0  # pending with no live job (requeued or not)


def live_jobs(task_name: str, tenant_id: UUID) -> set[str]:
    """Ids (`outbound_id`/`event_id`) of the tenant's `todo` or `doing` jobs of a task."""
    key = "outbound_id" if task_name == SEND_MESSAGE else "event_id"
    with connection.cursor() as cursor:
        cursor.execute(
            f"""SELECT args->>'{key}' FROM procrastinate_jobs
            WHERE task_name = %s AND status IN ('todo', 'doing')
            AND args->>'tenant_id' = %s""",
            [task_name, str(tenant_id)],
        )
        return {row[0] for row in cursor.fetchall()}


def sweep_tenant(tenant: LoadedTenant, now: datetime | None = None) -> SweepResult:
    now = now or timezone.now()
    unknown, requeued, stuck = _sweep_outbound(tenant, now)
    in_requeued, in_stuck = _sweep_inbound(tenant, now)
    return SweepResult(unknown, requeued, stuck, in_requeued, in_stuck)


def _sweep_outbound(tenant: LoadedTenant, now: datetime) -> tuple[int, int, int]:
    unknown = requeued = stuck = 0
    alive = live_jobs(SEND_MESSAGE, tenant.id)
    with tenant_tx(tenant.id):
        rows = list(
            OutboundMessage.objects.select_for_update(skip_locked=True)
            .select_related("contact")
            .filter(
                status__in=[OutboundMessage.Status.SENDING, OutboundMessage.Status.PENDING],
                created_at__lt=now - OUTBOUND_STUCK_AFTER,
            )
            .order_by("created_at")[:MAX_PER_SWEEP]
        )
        for message in rows:
            if str(message.id) in alive:
                continue
            if message.status == OutboundMessage.Status.SENDING:
                message.status = OutboundMessage.Status.UNKNOWN
                message.unknown_at = now
                message.last_error = "stuck while sending: no job left"
                message.save(update_fields=["status", "unknown_at", "last_error"])
                log.warning("outbound %s was stuck sending: left unknown", message.id)
                unknown += 1
            elif message.created_at >= now - OUTBOUND_REQUEUE_WINDOW:
                enqueue(
                    SEND_MESSAGE,
                    {"tenant_id": str(tenant.id), "outbound_id": str(message.id)},
                    queue=OUTBOUND,
                    lock=message_lock(tenant.id, message),
                    priority=send_priority(message.kind),
                )
                log.warning("outbound %s was pending with no job: queued again", message.id)
                requeued += 1
            else:
                stuck += 1
    return unknown, requeued, stuck


def _sweep_inbound(tenant: LoadedTenant, now: datetime) -> tuple[int, int]:
    requeued = stuck = 0
    alive = live_jobs(PROCESS_EVENT, tenant.id) | live_jobs(APPLY_STATUS, tenant.id)
    with tenant_tx(tenant.id):
        events = list(
            InboundEvent.objects.filter(
                status=InboundEvent.Status.PENDING,
                received_at__lt=now - INBOUND_STUCK_AFTER,
            ).order_by("received_at")[:MAX_PER_SWEEP]
        )
        for event in events:
            if str(event.id) in alive:
                continue
            stuck += 1
            if event.received_at < now - INBOUND_REQUEUE_WINDOW or not isinstance(
                event.payload, dict
            ):
                log.error("inbound event %s pending with no job: not queued again", event.id)
                continue
            try:
                ep = endpoint(tenant, event.channel)
                item = parse_stored(ep.adapter, event.payload, ep.channel)
            except Exception as e:  # a payload that no longer parses: a person looks at it
                log.error("inbound event %s not queued again: %s", event.id, type(e).__name__)
                continue
            ids = {"tenant_id": str(tenant.id), "event_id": str(event.id)}
            if isinstance(item, InboundItem):
                lock = conversation_lock(tenant.id, event.channel, item.external_id)
                enqueue(PROCESS_EVENT, ids, queue=process_event_queue(tenant.pack), lock=lock)
            else:
                enqueue(APPLY_STATUS, ids, queue=INBOUND)
            log.warning("inbound event %s was pending with no job: queued again", event.id)
            requeued += 1
    return requeued, stuck
