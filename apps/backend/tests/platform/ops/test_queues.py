"""Queue lag: age of the oldest ready and running job per queue, and `queue_lag:<queue>`."""

from datetime import datetime, timedelta
from typing import Any

import pytest
from django.db import connection, connections
from django.utils import timezone

from autobot.ops import check, health, queues
from autobot.ops.runbooks import runbook_path
from tests.helpers.disk import fake_disk
from tests.helpers.integration import wa_tenant

pytestmark = [
    pytest.mark.django_db(transaction=True, databases=["default", "owner"]),
    pytest.mark.usefixtures("clean_jobs"),
]


@pytest.fixture
def alerts(monkeypatch: pytest.MonkeyPatch, settings: Any) -> list[tuple[Any, ...]]:
    found: list[tuple[Any, ...]] = []
    settings.HEALTHCHECKS_PING_URL = ""
    settings.DEMO_TELEGRAM_TOKEN = ""
    settings.NOTIFY_BOT_TOKEN = ""
    monkeypatch.setattr(check, "send_ops_alert", lambda *args: found.append(args))
    monkeypatch.setattr(health, "tenant_health", lambda tenant: [])
    fake_disk(monkeypatch, 1)
    return found


def job(
    queue: str,
    *,
    queued_min_ago: float | None = None,
    scheduled_min_from_now: float | None = None,
    running_min: float | None = None,
    now: datetime,
) -> None:
    """A `todo` job queued `queued_min_ago` minutes ago (via its `deferred` event), or
    scheduled for a moment relative to now; or a job running for `running_min` minutes."""
    scheduled = (
        None if scheduled_min_from_now is None else now + timedelta(minutes=scheduled_min_from_now)
    )
    with connections["owner"].cursor() as cursor:
        cursor.execute(
            """INSERT INTO procrastinate_jobs(task_name, queue_name, status, args, scheduled_at)
            VALUES ('test', %s, 'todo', '{}', %s) RETURNING id""",
            [queue, scheduled],
        )
        (job_id,) = cursor.fetchone()
        if queued_min_ago is not None:
            cursor.execute(
                "UPDATE procrastinate_events SET at = %s WHERE job_id = %s AND type = 'deferred'",
                [now - timedelta(minutes=queued_min_ago), job_id],
            )
        if running_min is not None:
            cursor.execute("UPDATE procrastinate_jobs SET status = 'doing' WHERE id = %s", [job_id])
            cursor.execute(
                "UPDATE procrastinate_events SET at = %s WHERE job_id = %s AND type = 'started'",
                [now - timedelta(minutes=running_min), job_id],
            )


def lags(now: datetime) -> dict[str, queues.QueueLag]:
    with connection.cursor() as cursor:
        return {lag.queue_name: lag for lag in queues.queue_lags(cursor, now)}


def test_age_of_the_oldest_ready_and_running_job_per_queue() -> None:
    now = timezone.now()
    job("outbound", queued_min_ago=3, now=now)
    job("outbound", queued_min_ago=9, now=now)
    job("outbound", queued_min_ago=1, now=now)
    job("ops", running_min=4, now=now)
    found = lags(now)
    assert set(found) == {"outbound", "ops"}
    assert found["outbound"].pending == 3 and found["outbound"].running == 0
    assert found["outbound"].ready_age_s(now) == pytest.approx(9 * 60, abs=1)
    assert found["outbound"].running_age_s(now) is None
    assert found["ops"].pending == 0 and found["ops"].running == 1
    assert found["ops"].running_age_s(now) == pytest.approx(4 * 60, abs=1)


def test_jobs_scheduled_in_the_future_are_pending_but_not_late() -> None:
    now = timezone.now()
    job("periodic", scheduled_min_from_now=14, queued_min_ago=60, now=now)
    found = lags(now)["periodic"]
    assert found.pending == 1 and found.ready_age_s(now) is None


def test_age_is_measured_from_scheduled_at_not_from_creation() -> None:
    """run_periodic jobs are deferred up to 15 min ahead of their slot: the lag starts when
    the slot arrives."""
    now = timezone.now()
    job("periodic", scheduled_min_from_now=-2, queued_min_ago=30, now=now)
    assert lags(now)["periodic"].ready_age_s(now) == pytest.approx(120, abs=1)


@pytest.mark.parametrize(
    ("queue", "minutes", "expected"),
    [
        ("outbound", 6, True),
        ("outbound", 4, False),
        ("periodic", 21, True),
        ("periodic", 19, False),
        ("ops", 11, True),
        ("inbound", 30, False),  # covered by inbound_delay, never queue_lag
    ],
)
def test_queue_lag_alert_thresholds(
    tenants: Any, alerts: Any, queue: str, minutes: int, expected: bool
) -> None:
    tenants(wa_tenant())
    now = timezone.now()
    job(queue, queued_min_ago=minutes, now=now)
    check.run()
    raised = {a[0] for a in alerts}
    assert (f"queue_lag:{queue}" in raised) == expected
    assert ("inbound_delay" in raised) == (queue == "inbound")


def test_a_job_running_too_long_raises_queue_lag(tenants: Any, alerts: Any) -> None:
    tenants(wa_tenant())
    now = timezone.now()
    job("outbound", running_min=16, now=now)
    job("periodic", running_min=16, now=now)  # periodic jobs are allowed an hour
    check.run()
    raised = {a[0] for a in alerts}
    assert "queue_lag:outbound" in raised and "queue_lag:periodic" not in raised


def test_queue_lag_has_a_runbook() -> None:
    assert runbook_path("queue_lag:outbound") == "incidencias/cola-y-latido.md"


def test_the_query_only_touches_live_jobs_through_an_index() -> None:
    """With a large history of finished jobs the plan must not read them: it goes
    through the partial indexes procrastinate creates for `todo`/`doing` rows."""
    now = timezone.now()
    with connections["owner"].cursor() as cursor:
        cursor.execute(
            """INSERT INTO procrastinate_jobs(task_name, queue_name, status, args)
            SELECT 'test', 'outbound', 'succeeded', '{}' FROM generate_series(1, 20000)"""
        )
        cursor.execute("ANALYZE procrastinate_jobs")
        cursor.execute("EXPLAIN " + queues._SQL, [now])
        plan = "\n".join(row[0] for row in cursor.fetchall())
    assert "Seq Scan on procrastinate_jobs" not in plan, plan
