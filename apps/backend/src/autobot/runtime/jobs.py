"""Procrastinate app and job registry.

`procrastinate.contrib.django` builds the app on the `default` alias (fp_app) and imports
this module (PROCRASTINATE_AUTODISCOVER_MODULE_NAME = "runtime.jobs"), so every job is
declared here. The rest of `autobot.runtime` is imported inside each job because it
defers jobs through this module.

Rules for every job (CLAUDE.md): arguments, locks and logs carry only ids, never phone
numbers, user ids or personal data; every job is idempotent.
"""

import logging
import math
from typing import Any
from uuid import UUID

from asgiref.sync import sync_to_async
from django.db import InterfaceError as DjangoInterfaceError
from django.db import OperationalError as DjangoOperationalError
from django.db import close_old_connections
from django.utils import timezone
from procrastinate import BaseRetryStrategy, JobContext, RetryDecision, RetryStrategy
from procrastinate.contrib.django import app as app
from procrastinate.jobs import Job, Status
from procrastinate.periodic import PeriodicRegistry
from procrastinate.tasks import Task
from psycopg import InterfaceError as PsycopgInterfaceError
from psycopg import OperationalError as PsycopgOperationalError

from autobot.ops.logging import async_contextual, contextual
from core.errors import TransientError
from core.pack import Pack

log = logging.getLogger(__name__)

# Each queue shows what gets stuck, and each worker serves its own (ADR-023), so a slow
# dependency only ever holds the slots of its own queue. `ops` (ops_check, whose
# health checks make slow external calls one after another) is served by worker-periodic
# alone, so it never takes a slot of a worker that answers or sends.
INBOUND = "inbound"  # process_event (packs with no external call), apply_status, route_demo_event
# process_event of the packs that call Google Calendar (`Pack.needs_calendar`): the
# bulkhead that keeps a Google outage away from the other tenants' conversations.
INBOUND_EXT = "inbound_ext"
OUTBOUND = "outbound"  # send_message, send_notification
PERIODIC = "periodic"  # run_periodic, retention_cleanup
OPS = "ops"  # ops_check: listened to by worker-periodic only
QUEUES = (INBOUND, INBOUND_EXT, OUTBOUND, PERIODIC, OPS)

# Priority of the housekeeping tasks that share a worker with slow ones (`run_periodic`
# may hold a slot for minutes): they go first among the ready jobs of their queue.
HOUSEKEEPING_PRIORITY = 100
# A stalled job (its worker died) is not retried once it has this many attempts: one that
# keeps killing its worker (OOM on a poisonous payload) would otherwise loop every minute.
# `job.attempts` also counts the ordinary retries (up to `INBOUND_RETRIES`, or the
# `inbound_ext` database backoff), so the cap leaves room for them plus a few stalls.
STALLED_MAX_ATTEMPTS = 6

# Job names: a job is deferred by name, so modules that defer it do not import its task.
PROCESS_EVENT = "process_event"  # (tenant_id, event_id), lock conv:<h>
APPLY_STATUS = "apply_status"  # (tenant_id, event_id), no lock
SEND_MESSAGE = "send_message"  # (tenant_id, outbound_id), lock out:<h> (replies) / outp:<h>
SEND_NOTIFICATION = "send_notification"  # (tenant_id, notification_id), lock owner:<tenant>
ROUTE_DEMO_EVENT = "route_demo_event"  # (event_id) of demo_event, lock demo:<h>
DISPATCH_PERIODIC = "dispatch_periodic"  # (timestamp, pack, name): one per pack Periodic
RUN_PERIODIC = "run_periodic"  # (tenant_id, name, scheduled_at), queueing lock per both
RETRY_STALLED_JOBS = "retry_stalled_jobs"  # (timestamp): every minute
DISPATCH_OWNER_SUMMARIES = "dispatch_owner_summaries"  # (timestamp): hourly, platform-wide
SEND_OWNER_SUMMARY = "send_owner_summary"  # (tenant_id, year, month), queueing_lock summary:<t>
RECONCILE_UNKNOWN = "reconcile_unknown"  # (timestamp): every 5 minutes, platform-wide
HANDLE_OWNER_EVENT = "handle_owner_event"  # (event_id) of owner_event, lock ownerchat:<h>
OPS_DAILY_SUMMARY = "ops_daily_summary"  # (timestamp): hourly, sends once a day from 09:00

# Sends are exempt: their retries (`SendRetry` while a provider is down) pile up attempts
# by design, and a retried send never repeats the call (`sending` turns `unknown`, a
# notification is at-most-once), so it cannot keep killing its worker.
STALLED_CAP_EXEMPT = frozenset({SEND_MESSAGE, SEND_NOTIFICATION})


# What a job retries: a `TransientError` (a provider that may answer later) and the
# database errors of connection and concurrency, which usually pass on their own:
# `OperationalError` (connection lost, `lock_not_available`, deadlock, serialization
# failure) and `InterfaceError`, in Django's wrapping or psycopg's. Never
# `DataError`, `IntegrityError` or `ProgrammingError`: they are bugs, a retry would
# fail the same way.
RETRYABLE: tuple[type[Exception], ...] = (
    TransientError,
    DjangoOperationalError,
    DjangoInterfaceError,
    PsycopgOperationalError,
    PsycopgInterfaceError,
)

SUMMARY_RETRY = RetryStrategy(max_attempts=3, wait=300, retry_exceptions=RETRYABLE)

# `inbound` jobs are retried 3 times, on `RETRYABLE`, after 2, 4 and 8 s. `inbound_ext`
# ones, once (after 2 s): the Calendar client already tries twice and has a circuit
# breaker, and a job holding a slot through three more rounds is what made a Google
# outage starve everything (ADR-023). The last failed run answers with the degraded
# text instead of failing silently.
INBOUND_RETRIES = 3
INBOUND_EXT_RETRIES = 1
INBOUND_RETRY = RetryStrategy(
    max_attempts=INBOUND_RETRIES, exponential_wait=2, retry_exceptions=RETRYABLE
)
INBOUND_EXT_RETRY = RetryStrategy(
    max_attempts=INBOUND_EXT_RETRIES, exponential_wait=2, retry_exceptions=RETRYABLE
)


def process_event_queue(pack: Pack | None) -> str:
    """The queue of a tenant's `process_event`: `inbound_ext` when its pack calls Google
    Calendar, `inbound` otherwise. A contact belongs to one tenant, so its messages always
    land in the same queue, and the conversation lock keeps them in order."""
    return INBOUND_EXT if pack is not None and pack.needs_calendar else INBOUND


# A database blip (restart, failover, a saturated pool) lasts seconds to a minute: an
# `inbound_ext` job that hit one waits 5, 15 and 40 s (about a minute in all) before
# giving up, instead of leaving the message to the sweep (more than 5 minutes). Those
# waits hold no slot: the job is `todo` again, not running.
DB_ERRORS: tuple[type[Exception], ...] = tuple(e for e in RETRYABLE if e is not TransientError)
INBOUND_EXT_DB_WAITS_S = (5, 15, 40)


class ProcessEventRetry(BaseRetryStrategy):
    """`process_event` retries by the queue it runs in (`INBOUND_RETRY`,
    `INBOUND_EXT_RETRY`). In `inbound_ext`, a database error has its own, longer
    backoff (`INBOUND_EXT_DB_WAITS_S`); any other error keeps the single retry."""

    def get_retry_decision(self, *, exception: BaseException, job: Job) -> RetryDecision | None:
        if job.queue != INBOUND_EXT:
            return INBOUND_RETRY.get_retry_decision(exception=exception, job=job)
        if isinstance(exception, DB_ERRORS):
            if job.attempts < len(INBOUND_EXT_DB_WAITS_S):
                return RetryDecision(retry_in={"seconds": INBOUND_EXT_DB_WAITS_S[job.attempts]})
            return None
        return INBOUND_EXT_RETRY.get_retry_decision(exception=exception, job=job)


@app.task(queue=INBOUND, name=PROCESS_EVENT, pass_context=True, retry=ProcessEventRetry())
def process_event(context: JobContext, tenant_id: str, event_id: str) -> None:
    from autobot.runtime import process

    # Sync jobs run in worker threads: drop stale connections so they stay within the
    # connection budget.
    close_old_connections()
    try:
        process.process_event(
            UUID(tenant_id),
            UUID(event_id),
            last_attempt=is_last_attempt(context),
            first_attempt=context.job.attempts == 0,
        )
    finally:
        close_old_connections()


@app.task(queue=INBOUND, name=APPLY_STATUS, retry=INBOUND_RETRY)
def apply_status(tenant_id: str, event_id: str) -> None:
    from autobot.runtime import process

    close_old_connections()
    try:
        process.apply_status(UUID(tenant_id), UUID(event_id))
    finally:
        close_old_connections()


class SendRetryStrategy(BaseRetryStrategy):
    """`send_message` retries by time, not by count (ADR-024): a `SendRetry` (the provider
    asked for it, or could not be reached; the wait is already decided by `send_message`:
    its `retry_after` or a capped backoff with jitter) is always retried, and the message
    itself becomes `expired` once past its `expires_at`. The database errors of `RETRYABLE`
    (the message is still `pending`, or `sending`, which the retry leaves `unknown`: never
    resent) keep a bounded count; the outbound sweep queues again a `pending` message left
    with no job."""

    def get_retry_decision(self, *, exception: BaseException, job: Job) -> RetryDecision | None:
        from autobot.runtime.outbound import DB_ERROR_RETRIES, SendRetry, backoff_s

        if isinstance(exception, SendRetry):
            wait = exception.after_s if exception.after_s is not None else backoff_s(job.attempts)
        elif isinstance(exception, RETRYABLE) and job.attempts < DB_ERROR_RETRIES:
            wait = backoff_s(job.attempts)
        else:
            return None
        return RetryDecision(retry_in={"seconds": math.ceil(wait)})


class NotificationRetryStrategy(BaseRetryStrategy):
    """`send_notification` also retries by time (ADR-024): a `SendRetry` (no slot of the
    notify bot's rate limiter, a 429, or no connection) is always retried, after the wait
    `send_notification` already decided (else a capped backoff with jitter), and the notice
    itself becomes `expired` after `NOTICE_TTL`. Database errors keep a bounded count."""

    def get_retry_decision(self, *, exception: BaseException, job: Job) -> RetryDecision | None:
        from autobot.runtime.outbound import DB_ERROR_RETRIES, SendRetry, backoff_s

        if isinstance(exception, SendRetry) and exception.after_s is not None:
            wait = exception.after_s
        elif isinstance(exception, SendRetry) or (
            isinstance(exception, RETRYABLE) and job.attempts < DB_ERROR_RETRIES
        ):
            wait = backoff_s(job.attempts)
        else:
            return None
        return RetryDecision(retry_in={"seconds": math.ceil(wait)})


@app.task(queue=INBOUND, name=ROUTE_DEMO_EVENT, retry=INBOUND_RETRY)
def route_demo_event(event_id: str) -> None:
    from autobot.channels.demo import selector

    close_old_connections()
    try:
        selector.route_demo_event(UUID(event_id))
    finally:
        close_old_connections()


@app.task(queue=INBOUND, name=HANDLE_OWNER_EVENT, retry=INBOUND_RETRY)
def handle_owner_event(event_id: str) -> None:
    from autobot.owner import inbox

    close_old_connections()
    try:
        inbox.handle_owner_event(UUID(event_id))
    finally:
        close_old_connections()


@app.task(queue=OUTBOUND, name=SEND_MESSAGE, retry=SendRetryStrategy())
def send_message(tenant_id: str, outbound_id: str) -> None:
    from autobot.runtime import outbound

    close_old_connections()
    try:
        outbound.send_message(UUID(tenant_id), UUID(outbound_id))
    finally:
        close_old_connections()


@app.task(
    queue=OUTBOUND, name=SEND_NOTIFICATION, retry=NotificationRetryStrategy(), pass_context=True
)
def send_notification(context: JobContext, tenant_id: str, notification_id: str) -> None:
    from autobot.runtime import notifications

    close_old_connections()
    try:
        notifications.send_notification(
            UUID(tenant_id), UUID(notification_id), attempts=context.job.attempts
        )
    finally:
        close_old_connections()


@app.task(queue=PERIODIC, name=DISPATCH_PERIODIC)
@contextual
def dispatch_periodic(timestamp: int, pack: str, name: str) -> None:
    from autobot.runtime import periodic

    close_old_connections()
    try:
        periodic.dispatch(pack, name, timestamp)
    finally:
        close_old_connections()


# Twice, a minute apart, so a brief Calendar outage can pass.
@app.task(queue=PERIODIC, name=RUN_PERIODIC, retry=RetryStrategy(max_attempts=2, wait=60))
def run_periodic(tenant_id: str, name: str, scheduled_at: int) -> None:
    from autobot.runtime import periodic

    close_old_connections()
    try:
        periodic.run_periodic(UUID(tenant_id), name, scheduled_at)
    finally:
        close_old_connections()


@app.periodic(cron="* * * * *", periodic_id=RETRY_STALLED_JOBS)
@app.task(
    queue=PERIODIC,
    name=RETRY_STALLED_JOBS,
    queueing_lock=RETRY_STALLED_JOBS,
    pass_context=True,
    priority=HOUSEKEEPING_PRIORITY,
)
@async_contextual
async def retry_stalled_jobs(context: JobContext, timestamp: int) -> None:
    """Jobs left `doing` by a worker that died (no heartbeat for 30 s) keep their lock and
    would block the contact for good: Procrastinate does not retry them by itself.
    They go back to `todo`; every job is idempotent, and a `send_message` cut while
    `sending` ends `unknown`, never resent.

    A stalled job with a `queueing_lock` can collide with another job already queued
    under the same lock (e.g. the next `ops_check` tick): `retry_job` then fails and the
    stalled job would keep its `lock` forever. When that happens, it is marked `failed`
    instead, which releases the lock without retrying it.

    A job already retried `STALLED_MAX_ATTEMPTS` times is not retried again: it is
    `failed` and, if it is a `process_event`, its event gets the recovery text and
    `failed` (see `process.abandon_event`) instead of staying `pending`."""
    manager = context.app.job_manager
    for job in await manager.get_stalled_jobs():
        if job.attempts >= STALLED_MAX_ATTEMPTS and job.task_name not in STALLED_CAP_EXEMPT:
            await _give_up_stalled(manager, job)
            continue
        log.warning("retrying stalled job %s (%s)", job.id, job.task_name)
        try:
            await manager.retry_job(job)
        except Exception as e:  # it changed meanwhile (e.g. retried from the panel or `job_retry`)
            log.warning("stalled job %s not retried: %s", job.id, type(e).__name__)
            try:
                await manager.finish_job(job, status=Status.FAILED, delete_job=False)
            except Exception as e2:
                log.error("stalled job %s not failed either: %s", job.id, type(e2).__name__)


async def _give_up_stalled(manager: Any, job: Job) -> None:
    log.error(
        "stalled job %s (%s) failed %s times: not retried again",
        job.id,
        job.task_name,
        job.attempts,
    )
    if job.task_name == PROCESS_EVENT:
        try:
            await sync_to_async(_abandon_event)(job.task_kwargs)
        except Exception as e:
            log.error("stalled job %s: its event was not failed: %s", job.id, type(e).__name__)
    try:
        await manager.finish_job(job, status=Status.FAILED, delete_job=False)
    except Exception as e:
        log.error("stalled job %s not failed: %s", job.id, type(e).__name__)


def _abandon_event(task_kwargs: dict[str, Any]) -> None:
    from autobot.runtime import process

    close_old_connections()
    try:
        process.abandon_event(
            UUID(task_kwargs["tenant_id"]),
            UUID(task_kwargs["event_id"]),
            "worker died repeatedly while processing it",
        )
    finally:
        close_old_connections()


def cron_for(every_min: int) -> str:
    """A `Periodic.every_min` as cron (UTC): a divisor of 60 minutes, a divisor of 24
    hours, or once a day."""
    if 0 < every_min < 60 and 60 % every_min == 0:
        return f"*/{every_min} * * * *"
    hours, rest = divmod(every_min, 60)
    if rest == 0 and 0 < hours < 24 and 24 % hours == 0:
        return f"0 */{hours} * * *"
    if every_min == 24 * 60:
        return "0 0 * * *"
    raise ValueError(f"every_min={every_min} cannot be scheduled as cron")


def register_periodic(registry: PeriodicRegistry, packs: dict[str, Pack]) -> None:
    """One periodic dispatch per pack Periodic, with periodic_id `<pack>:<name>`."""
    task: Task[..., None, ...] = dispatch_periodic
    for pack in packs.values():
        for periodic in pack.periodic:
            registry.register_task(
                task=task,
                cron=cron_for(periodic.every_min),
                periodic_id=f"{pack.name}:{periodic.name}",
                configure_kwargs={"task_kwargs": {"pack": pack.name, "name": periodic.name}},
            )


def _register_pack_periodics() -> None:
    from packs.registry import PACKS

    register_periodic(app.periodic_registry, PACKS)


_register_pack_periodics()


def is_last_attempt(context: JobContext) -> bool:
    """`job.attempts` counts the runs that already failed: with 3 retries, the fourth run
    is the last one (with `inbound_ext`'s single retry, the second)."""
    retries = INBOUND_EXT_RETRIES if context.job.queue == INBOUND_EXT else INBOUND_RETRIES
    return context.job.attempts >= retries


@app.periodic(cron="*/5 * * * *", periodic_id="ops_check")
@app.task(
    queue=OPS,
    name="ops_check",
    queueing_lock="ops_check",
    lock="ops_check",
    priority=HOUSEKEEPING_PRIORITY,
)
@contextual
def ops_check(timestamp: int) -> None:
    from autobot.ops.check import run

    close_old_connections()
    try:
        run()
    finally:
        close_old_connections()


@app.periodic(cron="0 3 * * *", periodic_id="retention_cleanup")
@app.task(queue=PERIODIC, name="retention_cleanup", queueing_lock="retention_cleanup")
def retention_cleanup(timestamp: int) -> None:
    from autobot.runtime.retention import cleanup

    close_old_connections()
    try:
        cleanup()
    finally:
        close_old_connections()


# Ambiguous sends (ADR-026): resent once if still unknown after the wait for a delivery
# status, when a duplicate is harmless; also expires stale held owner notices.
@app.periodic(cron="*/5 * * * *", periodic_id=RECONCILE_UNKNOWN)
@app.task(queue=PERIODIC, name=RECONCILE_UNKNOWN, queueing_lock=RECONCILE_UNKNOWN)
def reconcile_unknown(timestamp: int) -> None:
    from autobot.runtime import reconcile

    close_old_connections()
    try:
        reconcile.reconcile_all(timezone.now())
    finally:
        close_old_connections()


# Procrastinate's own tables (ids only, no personal data): purged whatever
# RETENTION_CLEANUP_ENABLED says, which only governs customer data.
@app.periodic(cron="30 3 * * *", periodic_id="jobs_cleanup")
@app.task(queue=PERIODIC, name="jobs_cleanup", queueing_lock="jobs_cleanup")
def jobs_cleanup(timestamp: int) -> None:
    from autobot.runtime.retention import cleanup_jobs

    close_old_connections()
    try:
        cleanup_jobs()
    finally:
        close_old_connections()


# Hourly, platform-wide (not per-pack, so it does not use dispatch_periodic/run_periodic):
# dispatch_owner_summaries itself only acts on a tenant on its own day 1, past noon
# local time; ">=" rather than "==" recovers a send if the worker was down at noon.
@app.periodic(cron="0 * * * *", periodic_id=DISPATCH_OWNER_SUMMARIES)
@app.task(queue=PERIODIC, name=DISPATCH_OWNER_SUMMARIES, queueing_lock=DISPATCH_OWNER_SUMMARIES)
def dispatch_owner_summaries(timestamp: int) -> None:
    from autobot.runtime import summary

    close_old_connections()
    try:
        summary.dispatch_owner_summaries(timezone.now())
    finally:
        close_old_connections()


# Hourly: ops_daily_summary itself sends only once a day, on the first run past 09:00
# Madrid time (ADR-029); a later run recovers a send if the worker was down at nine.
@app.periodic(cron="5 * * * *", periodic_id=OPS_DAILY_SUMMARY)
@app.task(queue=PERIODIC, name=OPS_DAILY_SUMMARY, queueing_lock=OPS_DAILY_SUMMARY)
def ops_daily_summary(timestamp: int) -> None:
    from autobot.ops import daily

    close_old_connections()
    try:
        daily.send_daily_summary(timezone.now())
    finally:
        close_old_connections()


@app.task(queue=PERIODIC, name=SEND_OWNER_SUMMARY, retry=SUMMARY_RETRY)
def send_owner_summary(tenant_id: str, year: int, month: int) -> None:
    from autobot.runtime import summary

    close_old_connections()
    try:
        summary.send_owner_summary(UUID(tenant_id), year, month)
    finally:
        close_old_connections()
