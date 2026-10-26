"""Procrastinate app and job registry.

`procrastinate.contrib.django` builds the app on the `default` alias (fp_app) and imports
this module (PROCRASTINATE_AUTODISCOVER_MODULE_NAME = "jobs"), so every job is declared
here. The work itself lives in `flowpilot.runtime`, imported inside each job
because the runtime defers jobs through this module.

Rules for every job (CLAUDE.md): arguments, locks and logs carry only ids, never phone
numbers, user ids or personal data; every job is idempotent.
"""

import logging
import math
from uuid import UUID

from django.db import close_old_connections
from procrastinate import BaseRetryStrategy, JobContext, RetryDecision, RetryStrategy
from procrastinate.contrib.django import app as app
from procrastinate.jobs import Job
from procrastinate.periodic import PeriodicRegistry
from procrastinate.tasks import Task

from core.errors import TransientError
from core.pack import Pack
from flowpilot.ops.logging import async_contextual, contextual

log = logging.getLogger(__name__)

# One worker serves the three queues; separate queues show what gets stuck.
INBOUND = "inbound"  # process_event, apply_status, route_demo_event
OUTBOUND = "outbound"  # send_message, send_notification
PERIODIC = "periodic"  # run_periodic, ops_check, retention_cleanup
QUEUES = (INBOUND, OUTBOUND, PERIODIC)

# Job names: a job is deferred by name, so modules that defer it do not import its task.
PROCESS_EVENT = "process_event"  # (tenant_id, event_id), lock conv:<h>
APPLY_STATUS = "apply_status"  # (tenant_id, event_id), no lock
SEND_MESSAGE = "send_message"  # (tenant_id, outbound_id), lock out:<h>
SEND_NOTIFICATION = "send_notification"  # (tenant_id, notification_id), lock owner:<tenant>
ROUTE_DEMO_EVENT = "route_demo_event"  # (event_id) of demo_event, lock demo:<h>
DISPATCH_PERIODIC = "dispatch_periodic"  # (timestamp, pack, name): one per pack Periodic
RUN_PERIODIC = "run_periodic"  # (tenant_id, name, scheduled_at), queueing lock per both
RETRY_STALLED_JOBS = "retry_stalled_jobs"  # (timestamp): every 5 min

# `inbound` jobs are retried 3 times, only on TransientError, after 2, 4 and 8 s.
INBOUND_RETRIES = 3
INBOUND_RETRY = RetryStrategy(
    max_attempts=INBOUND_RETRIES, exponential_wait=2, retry_exceptions={TransientError}
)


@app.task(queue=INBOUND, name=PROCESS_EVENT, pass_context=True, retry=INBOUND_RETRY)
def process_event(context: JobContext, tenant_id: str, event_id: str) -> None:
    from flowpilot.runtime import process

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
    from flowpilot.runtime import process

    close_old_connections()
    try:
        process.apply_status(UUID(tenant_id), UUID(event_id))
    finally:
        close_old_connections()


class SendRetryStrategy(BaseRetryStrategy):
    """`send_message` is retried only when the provider asked for it (`RetryLater`, raised
    as `SendRetry`), after its `retry_after` or 2, 4, 8, 16 s. The message itself counts
    its attempts and becomes `failed` after the fifth."""

    def get_retry_decision(self, *, exception: BaseException, job: Job) -> RetryDecision | None:
        from flowpilot.runtime.outbound import MAX_SEND_ATTEMPTS, SendRetry

        if not isinstance(exception, SendRetry) or job.attempts >= MAX_SEND_ATTEMPTS:
            return None
        wait = exception.after_s if exception.after_s is not None else 2 ** (job.attempts + 1)
        return RetryDecision(retry_in={"seconds": math.ceil(wait)})


@app.task(queue=INBOUND, name=ROUTE_DEMO_EVENT, retry=INBOUND_RETRY)
def route_demo_event(event_id: str) -> None:
    from flowpilot.channels.demo import selector

    close_old_connections()
    try:
        selector.route_demo_event(UUID(event_id))
    finally:
        close_old_connections()


@app.task(queue=OUTBOUND, name=SEND_MESSAGE, retry=SendRetryStrategy())
def send_message(tenant_id: str, outbound_id: str) -> None:
    from flowpilot.runtime import outbound

    close_old_connections()
    try:
        outbound.send_message(UUID(tenant_id), UUID(outbound_id))
    finally:
        close_old_connections()


@app.task(queue=OUTBOUND, name=SEND_NOTIFICATION, retry=SendRetryStrategy(), pass_context=True)
def send_notification(context: JobContext, tenant_id: str, notification_id: str) -> None:
    from flowpilot.runtime import notifications
    from flowpilot.runtime.outbound import MAX_SEND_ATTEMPTS

    close_old_connections()
    try:
        notifications.send_notification(
            UUID(tenant_id),
            UUID(notification_id),
            last_attempt=context.job.attempts >= MAX_SEND_ATTEMPTS - 1,
        )
    finally:
        close_old_connections()


@app.task(queue=PERIODIC, name=DISPATCH_PERIODIC)
@contextual
def dispatch_periodic(timestamp: int, pack: str, name: str) -> None:
    from flowpilot.runtime import periodic

    close_old_connections()
    try:
        periodic.dispatch(pack, name, timestamp)
    finally:
        close_old_connections()


# Twice, a minute apart, so a brief Calendar outage can pass.
@app.task(queue=PERIODIC, name=RUN_PERIODIC, retry=RetryStrategy(max_attempts=2, wait=60))
def run_periodic(tenant_id: str, name: str, scheduled_at: int) -> None:
    from flowpilot.runtime import periodic

    close_old_connections()
    try:
        periodic.run_periodic(UUID(tenant_id), name, scheduled_at)
    finally:
        close_old_connections()


@app.periodic(cron="*/5 * * * *", periodic_id=RETRY_STALLED_JOBS)
@app.task(
    queue=PERIODIC, name=RETRY_STALLED_JOBS, queueing_lock=RETRY_STALLED_JOBS, pass_context=True
)
@async_contextual
async def retry_stalled_jobs(context: JobContext, timestamp: int) -> None:
    """Jobs left `doing` by a worker that died (no heartbeat for 30 s) keep their lock and
    would block the contact for good: Procrastinate does not retry them by itself.
    They go back to `todo`; every job is idempotent, and a `send_message` cut while
    `sending` ends `unknown`, never resent."""
    manager = context.app.job_manager
    for job in await manager.get_stalled_jobs():
        log.warning("retrying stalled job %s (%s)", job.id, job.task_name)
        try:
            await manager.retry_job(job)
        except Exception as e:  # it changed meanwhile (e.g. retried from the Admin)
            log.warning("stalled job %s not retried: %s", job.id, type(e).__name__)


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
    is the last one."""
    return context.job.attempts >= INBOUND_RETRIES


@app.periodic(cron="*/5 * * * *", periodic_id="ops_check")
@app.task(queue=PERIODIC, name="ops_check", queueing_lock="ops_check", lock="ops_check")
@contextual
def ops_check(timestamp: int) -> None:
    from flowpilot.ops.check import run

    close_old_connections()
    try:
        run()
    finally:
        close_old_connections()


@app.periodic(cron="0 3 * * *", periodic_id="retention_cleanup")
@app.task(queue=PERIODIC, name="retention_cleanup", queueing_lock="retention_cleanup")
def retention_cleanup(timestamp: int) -> None:
    from flowpilot.runtime.retention import cleanup

    close_old_connections()
    try:
        cleanup()
    finally:
        close_old_connections()
