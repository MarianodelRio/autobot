"""Queueing from synchronous code, atomic with the caller's transaction.

`procrastinate worker` swaps the global app's connector for a psycopg pool of its own
(`app.replace_connector(app.connector.get_worker_connector())`), so inside a job
`jobs.app.configure_task(...).defer(...)` inserts the new job through *that* pool,
outside the `tenant_tx` in progress: the job can be visible, and start, before the row it
needs is committed (a `send_message` that "finds no message" and leaves it `pending` for
good), and it survives a rollback.

Every enqueue done from sync code goes through `enqueue` instead. It uses a separate
Procrastinate `App` bound to a `DjangoConnector`, which inserts through the Django
connection of the current thread, the very one of the open transaction. The job is
invisible until commit, appears with it and disappears with a rollback. The commit
fires Procrastinate's NOTIFY trigger as usual (NOTIFY is delivered on commit). Tasks
are referenced by name: this module never imports `jobs`.
"""

from collections.abc import Mapping
from functools import cache
from typing import Any

from django.db import transaction
from procrastinate import App
from procrastinate.contrib.django.django_connector import DjangoConnector


@cache
def queue_app(alias: str = "default") -> App:
    """A Procrastinate app that defers through the Django connection `alias`."""
    return App(connector=DjangoConnector(alias=alias))


def enqueue(
    task: str,
    args: Mapping[str, Any],
    *,
    queue: str,
    lock: str | None = None,
    queueing_lock: str | None = None,
    schedule_in: dict[str, int] | None = None,
    priority: int | None = None,
    alias: str = "default",
) -> int:
    """Defer task `task` (by name) with the keyword `args` in the transaction open on
    connection `alias`: the job commits or rolls back with it (with no transaction open,
    it is inserted at once). `priority`: higher runs first among ready jobs of the queue
    (Procrastinate's, default 0). Returns the job id; raises `AlreadyEnqueued` if
    `queueing_lock` is taken (only that attempt is rolled back, never the caller's
    transaction). `args` are ids only (CLAUDE.md)."""
    extra: dict[str, Any] = {}
    if lock is not None:
        extra["lock"] = lock
    if schedule_in is not None:
        extra["schedule_in"] = schedule_in
    if priority is not None:
        extra["priority"] = priority
    deferrer = queue_app(alias)
    if queueing_lock is None:
        return deferrer.configure_task(task, queue=queue, **extra).defer(**args)
    # A taken queueing_lock fails the INSERT: inside a transaction that would abort it
    # whole, so the attempt runs in a savepoint and only it is rolled back.
    with transaction.atomic(using=alias):
        return deferrer.configure_task(
            task, queue=queue, queueing_lock=queueing_lock, **extra
        ).defer(**args)
