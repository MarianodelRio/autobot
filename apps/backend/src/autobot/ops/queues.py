"""How far behind each job queue is: the age of its oldest ready job, and of its oldest
running one.

One query over `procrastinate_jobs`, shared by the panel's System screen and ops_check.
It only touches rows in `todo` or `doing`, which the partial indexes procrastinate
creates (`procrastinate_jobs_id_lock_idx_v1`, `..._priority_idx_v1`) serve, so its cost
follows the backlog and never the history of finished jobs. The event lookups go
through `procrastinate_events.job_id`'s index, one per live job.

A queued job is "ready" when it has no `scheduled_at` or that time has passed. Its age is
measured from `scheduled_at` when there is one (run_periodic jobs are deliberately
spread over a window, so the creation time would read as lag), otherwise from the last
event that put it in the queue. A running job's age is measured from its `started` event.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any

# Seconds an oldest ready job may wait before ops_check raises `queue_lag:<queue>`.
# Inbound queues are absent on purpose: `inbound_delay` already covers them (2 min), see
# `INBOUND_DELAY_S` and docs/referencia/alertas.md.
LAG_THRESHOLD_S: dict[str, int] = {"outbound": 300, "periodic": 1200, "ops": 600}
INBOUND_DELAY_S = 120
INBOUND_QUEUES = ("inbound", "inbound_ext")
# A job `doing` for longer than this is suspected stuck (retry_stalled_jobs only frees
# those whose worker stopped beating). Periodic holds the long retention/sweep jobs.
STUCK_S: dict[str, int] = {"periodic": 3600}
DEFAULT_STUCK_S = 900

_SQL = """
WITH live AS (
    SELECT j.queue_name, j.status, j.scheduled_at,
        CASE j.status WHEN 'todo' THEN COALESCE(j.scheduled_at, (
            SELECT max(e.at) FROM procrastinate_events e WHERE e.job_id = j.id
            AND e.type IN ('deferred', 'deferred_for_retry', 'scheduled')))
        ELSE (SELECT max(e.at) FROM procrastinate_events e
            WHERE e.job_id = j.id AND e.type = 'started') END AS since
    FROM procrastinate_jobs j WHERE j.status IN ('todo', 'doing')
)
SELECT queue_name,
    count(*) FILTER (WHERE status = 'todo'),
    count(*) FILTER (WHERE status = 'doing'),
    min(since) FILTER (WHERE status = 'todo'
        AND (scheduled_at IS NULL OR scheduled_at <= %s)),
    min(since) FILTER (WHERE status = 'doing')
FROM live GROUP BY queue_name
"""


@dataclass(frozen=True)
class QueueLag:
    queue_name: str
    pending: int  # all `todo` jobs, future-scheduled ones included
    running: int
    oldest_ready_at: datetime | None
    oldest_running_at: datetime | None

    def ready_age_s(self, now: datetime) -> float | None:
        at = self.oldest_ready_at
        return max((now - at).total_seconds(), 0.0) if at else None

    def running_age_s(self, now: datetime) -> float | None:
        at = self.oldest_running_at
        return max((now - at).total_seconds(), 0.0) if at else None

    def as_row(self, now: datetime) -> dict[str, Any]:
        return {
            "queue_name": self.queue_name,
            "pending": self.pending,
            "oldest": self.oldest_ready_at,
            "age_s": self.ready_age_s(now),
            "running": self.running,
            "running_age_s": self.running_age_s(now),
        }


def queue_lags(cursor: Any, now: datetime) -> list[QueueLag]:
    """Queues with live jobs, by name. A queue without any does not appear."""
    cursor.execute(_SQL, [now])
    return sorted((QueueLag(*row) for row in cursor.fetchall()), key=lambda lag: lag.queue_name)
