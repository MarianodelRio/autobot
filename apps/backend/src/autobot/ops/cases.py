"""The cases of an incident (ADR-031), computed live from their tables: the same filters
count them in ops_check (inside a tenant's `tenant_tx`, as fp_app) and list them in the
panel (`.using("owner")`, filtered by the incident's tenant).

No case is ever copied into `ops_alert`: only how many there are and the newest time.

A case's time is when it became a failure (`failed_at`; `unknown_at` for an ambiguous
send), never when its row was created: a resend of an old ambiguous send that then fails
is a new case after the watermark. Rows from before `failed_at` existed fall back to
`created_at`. Every queryset here is annotated with that time as `case_at`."""

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from django.db.models import Count, F, Max, Q, QuerySet
from django.db.models.functions import Coalesce

from autobot.channels.adapters import channel_type
from autobot.channels.base import ChannelType
from autobot.ops.incidents import REJECTED_EXCLUDED
from autobot.ops.send_errors import SendErrorClass, classify
from autobot.runtime.models import Channel, Notification, OutboundMessage
from autobot.runtime.outbound import RECONCILE_WAIT
from autobot.tenancy.registry import LoadedTenant

# An `unknown` send still undecided after the wait for a status and the reconcile that
# follows (ADR-026): neither resolved it, a person must. No upper bound: it stays a case
# until someone marks it sent, resends or discards it.
AMBIGUOUS_AFTER = RECONCILE_WAIT + timedelta(minutes=10)
# `owner_unlinked`: the notices held for an owner with no chat, and those that expired so
# (`reconcile.expire_held`, after NOTICE_TTL) in the last 24 h, or the condition would
# close with nothing fixed.
HELD_WINDOW = timedelta(hours=24)


@dataclass(frozen=True)
class Tally:
    count: int
    last: datetime | None


def _failed_at() -> Coalesce:
    return Coalesce(F("failed_at"), F("created_at"))


def ambiguous(qs: QuerySet[OutboundMessage], now: datetime) -> QuerySet[OutboundMessage]:
    return qs.filter(
        status=OutboundMessage.Status.UNKNOWN, unknown_at__lt=now - AMBIGUOUS_AFTER
    ).annotate(case_at=Coalesce(F("unknown_at"), F("created_at")))


def lost_notices(qs: QuerySet[Notification], after: datetime) -> QuerySet[Notification]:
    """`notification_failed`: a notice claimed `failed` (rejected or ambiguous, never
    resent blindly) or `expired` (undelivered after NOTICE_TTL) after the watermark."""
    return qs.annotate(case_at=_failed_at()).filter(
        status__in=(Notification.Status.FAILED, Notification.Status.EXPIRED), case_at__gt=after
    )


def held_notices(qs: QuerySet[Notification], now: datetime) -> QuerySet[Notification]:
    return qs.filter(
        status__in=(Notification.Status.HELD, Notification.Status.EXPIRED),
        created_at__gte=now - HELD_WINDOW,
    ).annotate(case_at=F("created_at"))


def tally(qs: QuerySet[Any]) -> Tally:
    """How many cases and the newest case time (`case_at`)."""
    row = qs.aggregate(n=Count("id"), last=Max("case_at"))
    return Tally(row["n"], row["last"])


# ── Rejected sends, by error class ──────────────────────────────────────────


def _type_of(tenant: LoadedTenant | None, channel: str) -> ChannelType:
    if channel == Channel.MAIN and (tenant is None or tenant.document.channel is None):
        return "whatsapp"  # never expected: a demo tenant sends through its door only
    if tenant is None:
        return "whatsapp" if channel == Channel.DEMO_WA else "telegram"
    return channel_type(tenant, channel)


def message_class(tenant: LoadedTenant | None, channel: str, last_error: str) -> SendErrorClass:
    return classify(_type_of(tenant, channel), last_error)


type Pair = tuple[str, str]  # (channel, last_error)


def rejected_pairs(
    qs: QuerySet[OutboundMessage], tenant: LoadedTenant | None, after: datetime
) -> dict[str, list[Pair]]:
    """Error class -> the (channel, last_error) pairs of the sends that became `failed`
    after `after`. Grouped in SQL: a tenant has few distinct error texts, however many
    sends."""
    out: dict[str, list[Pair]] = defaultdict(list)
    rows = (
        qs.annotate(case_at=_failed_at())
        .filter(status=OutboundMessage.Status.FAILED, case_at__gt=after)
        .values_list("channel", "last_error")
        .distinct()
        .order_by()
    )
    for channel, last_error in rows:
        cls = message_class(tenant, channel, last_error or "")
        if cls not in REJECTED_EXCLUDED:
            out[cls].append((channel, last_error))
    return dict(out)


def rejected(
    qs: QuerySet[OutboundMessage], pairs: list[Pair], after: datetime
) -> QuerySet[OutboundMessage]:
    """The sends that became `failed` after `after` with one of `pairs` (one error class)."""
    match = Q()
    for channel, last_error in pairs:
        match |= Q(channel=channel, last_error=last_error)
    qs = qs.annotate(case_at=_failed_at())
    if not pairs:
        return qs.none()
    return qs.filter(match, status=OutboundMessage.Status.FAILED, case_at__gt=after)


# ── Failed jobs ─────────────────────────────────────────────────────────────

# A job's case time is its latest `failed` event; it is a case while it is still `failed`.
# (`retry_stalled_jobs` finishes a stalled job that only collided with a queued one under
# the same queueing lock as `aborted`, not `failed`: runtime/jobs.py.)
FAILED_JOBS_SQL = """
    SELECT j.task_name, count(DISTINCT j.id), max(e.at)
    FROM procrastinate_jobs j JOIN procrastinate_events e ON e.job_id = j.id
    WHERE e.type = 'failed' AND j.status = 'failed' AND e.at > %s {task}
    GROUP BY j.task_name"""


def failed_jobs(cursor: Any, after: datetime, task: str | None = None) -> dict[str, Tally]:
    """Task -> its failed jobs whose `failed` event is after `after`."""
    if task is None:
        cursor.execute(FAILED_JOBS_SQL.format(task=""), [after])
    else:
        cursor.execute(FAILED_JOBS_SQL.format(task="AND j.task_name = %s"), [after, task])
    return {name: Tally(int(n), last) for name, n, last in cursor.fetchall()}
