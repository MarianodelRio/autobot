"""Which failures a job retries: provider/transient and database connection or
concurrency errors; never a bug (DataError, IntegrityError, ProgrammingError)."""

from datetime import UTC, datetime

import psycopg
import pytest
from django import db
from procrastinate.jobs import Job

from autobot.runtime.jobs import (
    INBOUND,
    INBOUND_EXT,
    INBOUND_RETRY,
    SUMMARY_RETRY,
    NotificationRetryStrategy,
    ProcessEventRetry,
    SendRetryStrategy,
    is_last_attempt,
)
from autobot.runtime.outbound import SendRetry
from core.errors import TransientError


def job(attempts: int = 0, queue: str = "q") -> Job:
    return Job(id=1, queue=queue, lock=None, queueing_lock=None, task_name="t", attempts=attempts)


@pytest.mark.parametrize(
    "exc",
    [
        TransientError("x"),
        db.OperationalError("connection lost"),
        db.InterfaceError("closed"),
        psycopg.errors.LockNotAvailable("lock"),
        psycopg.errors.DeadlockDetected("deadlock"),
        psycopg.errors.SerializationFailure("serialization"),
    ],
)
def test_transient_and_connection_errors_are_retried(exc: Exception) -> None:
    for strategy in (INBOUND_RETRY, SUMMARY_RETRY, SendRetryStrategy()):
        assert strategy.get_retry_decision(exception=exc, job=job()) is not None


@pytest.mark.parametrize(
    "exc",
    [db.DataError("bad"), db.IntegrityError("dup"), db.ProgrammingError("sql"), ValueError("x")],
)
def test_bugs_are_never_retried(exc: Exception) -> None:
    for strategy in (INBOUND_RETRY, SUMMARY_RETRY, SendRetryStrategy()):
        assert strategy.get_retry_decision(exception=exc, job=job()) is None


def test_retries_are_bounded() -> None:
    assert INBOUND_RETRY.get_retry_decision(exception=TransientError("x"), job=job(3)) is None


def test_notices_retry_by_time_not_by_count() -> None:
    """A 429 or a missing slot of the limiter never exhausts attempts (the notice expires
    after `NOTICE_TTL`); database errors keep a bounded count."""
    notices = NotificationRetryStrategy()
    for attempts in (0, 5, 50, 500):
        decision = notices.get_retry_decision(exception=SendRetry(3), job=job(attempts))
        assert decision is not None
    assert notices.get_retry_decision(exception=SendRetry(None), job=job(9)) is not None
    error = db.OperationalError("connection lost")
    assert notices.get_retry_decision(exception=error, job=job(4)) is not None
    assert notices.get_retry_decision(exception=error, job=job(5)) is None


def test_send_message_retries_by_time_not_by_count() -> None:
    """ADR-024: a provider that says "later" is retried however many times it already did
    (the message expires by its `expires_at`); database errors keep a bounded count."""
    strategy = SendRetryStrategy()
    for attempts in (0, 5, 50, 500):
        assert strategy.get_retry_decision(exception=SendRetry(3), job=job(attempts)) is not None
    error = db.OperationalError("connection lost")
    assert strategy.get_retry_decision(exception=error, job=job(4)) is not None
    assert strategy.get_retry_decision(exception=error, job=job(5)) is None


def test_process_event_gets_three_retries_in_inbound_and_one_in_inbound_ext() -> None:
    """ADR-023: a job holding a Calendar slot through more rounds is what starved everyone."""
    strategy = ProcessEventRetry()
    error = TransientError("x")
    inbound = [strategy.get_retry_decision(exception=error, job=job(n, INBOUND)) for n in range(4)]
    assert [d is not None for d in inbound] == [True, True, True, False]
    ext = [strategy.get_retry_decision(exception=error, job=job(n, INBOUND_EXT)) for n in range(3)]
    assert [d is not None for d in ext] == [True, False, False]
    assert ext[0] is not None and ext[0].retry_at is not None


def test_the_last_attempt_follows_the_queue() -> None:
    from types import SimpleNamespace
    from typing import Any

    def context(attempts: int, queue: str) -> Any:
        return SimpleNamespace(job=job(attempts, queue))

    assert [is_last_attempt(context(n, INBOUND)) for n in range(4)] == [False] * 3 + [True]
    assert [is_last_attempt(context(n, INBOUND_EXT)) for n in range(2)] == [False, True]


def test_inbound_ext_waits_about_a_minute_on_database_errors() -> None:
    """A 5-10 s blip does not exhaust the retries of `inbound_ext`; other errors keep the
    single retry."""
    strategy = ProcessEventRetry()
    for error in (db.OperationalError("lost"), psycopg.OperationalError("lost")):
        waits = []
        now = datetime.now(UTC)
        for n in range(5):
            decision = strategy.get_retry_decision(exception=error, job=job(n, INBOUND_EXT))
            waits.append(
                decision and decision.retry_at and round((decision.retry_at - now).total_seconds())
            )
        assert waits == [5, 15, 40, None, None]
    # `inbound` is unchanged and a TransientError in `inbound_ext` keeps its one retry.
    assert strategy.get_retry_decision(exception=db.OperationalError("x"), job=job(2, INBOUND))
    assert (
        strategy.get_retry_decision(exception=db.OperationalError("x"), job=job(3, INBOUND)) is None
    )
    transient = TransientError("x")
    assert strategy.get_retry_decision(exception=transient, job=job(0, INBOUND_EXT)) is not None
    assert strategy.get_retry_decision(exception=transient, job=job(1, INBOUND_EXT)) is None
    # A bug is never retried.
    assert strategy.get_retry_decision(exception=ValueError("x"), job=job(0, INBOUND_EXT)) is None


def test_the_housekeeping_tasks_have_a_high_priority() -> None:
    """They share worker-periodic with slow `run_periodic` jobs. The periodic deferrer
    defers with `task.configure(...)`, which falls back to the task's own priority."""
    from autobot.runtime.jobs import HOUSEKEEPING_PRIORITY, app

    for name in ("retry_stalled_jobs", "ops_check"):
        task = app.tasks[name]
        assert task.priority == HOUSEKEEPING_PRIORITY > 0
        assert task.configure().job.priority == HOUSEKEEPING_PRIORITY
    assert app.tasks["run_periodic"].priority == 0
