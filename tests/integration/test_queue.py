"""Procrastinate queue (design.md §7.5, T-2.5): a job is deferred and run by a worker,
and jobs sharing a lock run one at a time, in creation order. Transactional: the worker
only sees committed jobs, as in production."""

import threading
import time
from collections.abc import Iterator

import pytest
from django.db import connections
from procrastinate.contrib.django.django_connector import DjangoConnector

from flowpilot.jobs import INBOUND, QUEUES, app

pytestmark = pytest.mark.django_db(transaction=True, databases=["default", "owner"])

# What the test jobs did, in order: (label, "start" | "end", monotonic time).
EVENTS: list[tuple[str, str, float]] = []


@app.task(queue=INBOUND, name="tests.record")
def record(label: str, seconds: float = 0.0) -> None:
    EVENTS.append((label, "start", time.monotonic()))
    time.sleep(seconds)
    EVENTS.append((label, "end", time.monotonic()))


@pytest.fixture(autouse=True)
def clean_jobs() -> Iterator[None]:
    """The flush does not reach Procrastinate's tables (unmanaged models)."""
    EVENTS.clear()
    yield
    with connections["owner"].cursor() as cursor:
        cursor.execute("DELETE FROM procrastinate_jobs")


def run_worker(concurrency: int = 4) -> None:
    """Run a worker in this process until no job is left to do, with the same connector
    as `manage.py procrastinate worker` (its own psycopg pool on the default alias).
    With wait=False a worker stops as soon as it finds nothing it may take (the rest may
    be waiting on a lock), so it is started again while jobs remain."""
    assert isinstance(app.connector, DjangoConnector)
    for _ in range(20):
        with app.replace_connector(app.connector.get_worker_connector()) as worker_app:
            worker_app.run_worker(
                queues=list(QUEUES),
                concurrency=concurrency,
                wait=False,
                install_signal_handlers=False,
                listen_notify=False,
            )
        if "todo" not in job_statuses():
            return
    raise AssertionError("jobs left to do")


def job_statuses() -> list[str]:
    with connections["owner"].cursor() as cursor:
        cursor.execute("SELECT status FROM procrastinate_jobs ORDER BY id")
        return [status for (status,) in cursor.fetchall()]


def test_a_job_is_deferred_and_run() -> None:
    record.defer(label="hello")
    assert job_statuses() == ["todo"]
    run_worker()
    assert [(label, what) for label, what, _ in EVENTS] == [("hello", "start"), ("hello", "end")]
    assert job_statuses() == ["succeeded"]


def test_jobs_with_the_same_lock_run_in_order_and_never_at_once() -> None:
    # The first job is slow: with 4 concurrent slots, only the lock keeps the others out.
    for i, seconds in enumerate([0.3, 0.0, 0.1, 0.0]):
        record.configure(lock="conv:abc").defer(label=f"m{i}", seconds=seconds)
    run_worker(concurrency=4)

    assert [label for label, what, _ in EVENTS if what == "start"] == ["m0", "m1", "m2", "m3"]
    ends = [at for _, what, at in EVENTS if what == "end"]
    starts = [at for _, what, at in EVENTS if what == "start"]
    assert all(start >= end for start, end in zip(starts[1:], ends, strict=False))


B_STARTED = threading.Event()


@app.task(queue=INBOUND, name="tests.wait_for_b")
def wait_for_b() -> None:
    EVENTS.append(("a", "saw_b" if B_STARTED.wait(timeout=10) else "timeout", time.monotonic()))


@app.task(queue=INBOUND, name="tests.start_b")
def start_b() -> None:
    B_STARTED.set()


def test_jobs_with_different_locks_can_run_at_once() -> None:
    # "a" only finishes once "b" has started: both must be running at the same time.
    B_STARTED.clear()
    wait_for_b.configure(lock="conv:a").defer()
    start_b.configure(lock="conv:b").defer()
    run_worker(concurrency=2)
    assert [what for label, what, _ in EVENTS if label == "a"] == ["saw_b"]
