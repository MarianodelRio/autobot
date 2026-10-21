"""Procrastinate app and job registry (design.md §4.4, §7.5).

`procrastinate.contrib.django` builds the app on the `default` alias (fp_app) and imports
this module (PROCRASTINATE_AUTODISCOVER_MODULE_NAME = "jobs"), so every job is declared
here (`process_event` and `apply_status` from T-3.5; `send_message`, `run_periodic`…
with later tasks). The work itself lives in `flowpilot.runtime`, imported inside each job
because the runtime defers jobs through this module.

Rules for every job (CLAUDE.md): arguments, locks and logs carry only ids, never phone
numbers, user ids or personal data; every job is idempotent.
"""

import math
from uuid import UUID

from django.db import close_old_connections
from procrastinate import BaseRetryStrategy, JobContext, RetryDecision, RetryStrategy
from procrastinate.contrib.django import app as app
from procrastinate.jobs import Job

from core.errors import TransientError

# One worker serves the three queues (§7.5); separate queues show what gets stuck.
INBOUND = "inbound"  # process_event, apply_status, route_test_update
OUTBOUND = "outbound"  # send_message, send_notification
PERIODIC = "periodic"  # run_periodic, ops_check, retention_cleanup
QUEUES = (INBOUND, OUTBOUND, PERIODIC)

# Job names: a job is deferred by name, so modules that defer it do not import its task.
PROCESS_EVENT = "process_event"  # (tenant_id, event_id), lock conv:<h>
APPLY_STATUS = "apply_status"  # (tenant_id, event_id), no lock
SEND_MESSAGE = "send_message"  # (tenant_id, outbound_id), lock out:<h> (T-3.6)
SEND_NOTIFICATION = "send_notification"  # (tenant_id, notification_id), lock owner:<tenant> (T-6.1)

# `inbound` jobs are retried 3 times, only on TransientError, after 2, 4 and 8 s (§7.5).
INBOUND_RETRIES = 3
INBOUND_RETRY = RetryStrategy(
    max_attempts=INBOUND_RETRIES, exponential_wait=2, retry_exceptions={TransientError}
)


@app.task(queue=INBOUND, name=PROCESS_EVENT, pass_context=True, retry=INBOUND_RETRY)
def process_event(context: JobContext, tenant_id: str, event_id: str) -> None:
    from flowpilot.runtime import process

    # Sync jobs run in worker threads: drop stale connections so they stay within §4.2.
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
    its attempts and becomes `failed` after the fifth (§7.4)."""

    def get_retry_decision(self, *, exception: BaseException, job: Job) -> RetryDecision | None:
        from flowpilot.runtime.outbound import MAX_SEND_ATTEMPTS, SendRetry

        if not isinstance(exception, SendRetry) or job.attempts >= MAX_SEND_ATTEMPTS:
            return None
        wait = exception.after_s if exception.after_s is not None else 2 ** (job.attempts + 1)
        return RetryDecision(retry_in={"seconds": math.ceil(wait)})


@app.task(queue=OUTBOUND, name=SEND_MESSAGE, retry=SendRetryStrategy())
def send_message(tenant_id: str, outbound_id: str) -> None:
    from flowpilot.runtime import outbound

    close_old_connections()
    try:
        outbound.send_message(UUID(tenant_id), UUID(outbound_id))
    finally:
        close_old_connections()


def is_last_attempt(context: JobContext) -> bool:
    """`job.attempts` counts the runs that already failed: with 3 retries, the fourth run
    is the last one."""
    return context.job.attempts >= INBOUND_RETRIES
