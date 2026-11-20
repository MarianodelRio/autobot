"""Which failures a job retries: provider/transient and database connection or
concurrency errors; never a bug (DataError, IntegrityError, ProgrammingError)."""

import psycopg
import pytest
from django import db
from procrastinate.jobs import Job

from autobot.runtime.jobs import INBOUND_RETRY, SUMMARY_RETRY, SendRetryStrategy
from autobot.runtime.outbound import SendRetry
from core.errors import TransientError


def job(attempts: int = 0) -> Job:
    return Job(id=1, queue="q", lock=None, queueing_lock=None, task_name="t", attempts=attempts)


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
    assert SendRetryStrategy().get_retry_decision(exception=SendRetry(1), job=job(1)) is not None
