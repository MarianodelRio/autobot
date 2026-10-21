"""Periodic work of the packs (design.md §7.6, T-3.7) with the toy pack's
`daily_summary` and the real database and queue."""

import asyncio
import time
from typing import Any

import pytest
from django.db import connections
from procrastinate.contrib.django.django_connector import DjangoConnector
from procrastinate.periodic import PeriodicRegistry

from flowpilot.jobs import DISPATCH_PERIODIC, PERIODIC, app, cron_for, register_periodic
from flowpilot.runtime import periodic
from flowpilot.runtime.models import Notification
from flowpilot.tenancy.registry import LoadedTenant, get_registry
from tests.integration.helpers import jobs, wa_tenant
from tests.tenancy.helpers import PACKS, WA_SECRETS

pytestmark = [
    pytest.mark.django_db(transaction=True, databases=["default", "owner"]),
    pytest.mark.usefixtures("clean_jobs"),
]

OWNER = {"telegram_chat_id": 987654321, "notify": ["daily"]}


def tenant(slug: str) -> LoadedTenant:
    return get_registry().by_slug[slug]


def run_jobs() -> None:
    assert isinstance(app.connector, DjangoConnector)
    with app.replace_connector(app.connector.get_worker_connector()) as worker_app:
        worker_app.run_worker(
            queues=[PERIODIC], wait=False, install_signal_handlers=False, listen_notify=False
        )


# ── Registration ──────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("every_min", "cron"),
    [
        (15, "*/15 * * * *"),
        (5, "*/5 * * * *"),
        (60, "0 */1 * * *"),
        (360, "0 */6 * * *"),
        (1440, "0 0 * * *"),
    ],
)
def test_cron_for(every_min: int, cron: str) -> None:
    assert cron_for(every_min) == cron


@pytest.mark.parametrize("every_min", [0, 7, 90, 2880])
def test_unschedulable_periods_fail_loudly(every_min: int) -> None:
    with pytest.raises(ValueError):
        cron_for(every_min)


def test_each_pack_periodic_is_a_procrastinate_periodic_task() -> None:
    registry = PeriodicRegistry()  # type: ignore[no-untyped-call]
    register_periodic(registry, PACKS)
    (task,) = registry.periodic_tasks.values()
    assert (task.task.name, task.periodic_id, task.cron) == (
        DISPATCH_PERIODIC,
        "toy:daily_summary",
        "0 0 * * *",
    )
    assert task.configure_kwargs == {"task_kwargs": {"pack": "toy", "name": "daily_summary"}}


# ── Dispatch ──────────────────────────────────────────────────────────────


def test_dispatch_queues_one_run_per_active_tenant(tenants: Any) -> None:
    tenants(
        wa_tenant("wa"),
        wa_tenant("onb", status="onboarding"),
        wa_tenant("pau", status="paused"),
        wa_tenant("off", status="offboarded"),
        wa_tenant("bad", config={"colors": 1}),
        wa_tenant("nosec"),  # active, but its main channel has no secrets
        secrets={slug: WA_SECRETS for slug in ("wa", "onb", "pau", "off", "bad")},
    )
    assert periodic.dispatch("toy", "daily_summary", 1791194400) == 1
    (job,) = jobs()
    assert job[0] == "run_periodic" and job[3] == "periodic"
    assert job[2] == {
        "tenant_id": str(tenant("wa").id),
        "name": "daily_summary",
        "scheduled_at": 1791194400,
    }


def test_a_pending_run_is_not_queued_twice(tenants: Any) -> None:
    tenants(wa_tenant())
    assert periodic.dispatch("toy", "daily_summary", 1791194400) == 1
    assert periodic.dispatch("toy", "daily_summary", 1791194400) == 0  # queueing lock
    assert len(jobs()) == 1


def test_a_scheduled_instant_is_deferred_only_once(tenants: Any) -> None:
    """Procrastinate's own guarantee, on which the dispatch relies."""
    tenants(wa_tenant())
    timestamp = int(time.time())
    job = app.configure_task(
        DISPATCH_PERIODIC,
        queue=PERIODIC,
        task_kwargs={"timestamp": timestamp, "pack": "toy", "name": "daily_summary"},
    ).job

    async def defer_twice() -> list[int | None]:
        assert isinstance(app.connector, DjangoConnector)
        worker_app = app.with_connector(app.connector.get_worker_connector())
        async with worker_app.open_async():
            manager = worker_app.job_manager
            return [
                await manager.defer_periodic_job(job, "toy:daily_summary", timestamp),
                await manager.defer_periodic_job(job, "toy:daily_summary", timestamp),
            ]

    first, second = asyncio.run(defer_twice())
    assert first is not None and second is None


# ── run_periodic ──────────────────────────────────────────────────────────


def test_run_applies_the_actions_once(tenants: Any) -> None:
    tenants(wa_tenant(owner=OWNER))
    now = int(time.time())
    periodic.run_periodic(tenant("wa").id, "daily_summary", now)
    periodic.run_periodic(tenant("wa").id, "daily_summary", now)  # same stable key
    (row,) = Notification.objects.using("owner").all()
    assert row.idem_key.startswith("daily:") and row.kind == "daily"
    assert [j[0] for j in jobs()] == ["send_notification"]


def test_a_late_run_is_dropped_and_logged(tenants: Any, caplog: pytest.LogCaptureFixture) -> None:
    tenants(wa_tenant(owner=OWNER))
    periodic.run_periodic(tenant("wa").id, "daily_summary", int(time.time()) - 61 * 60)
    assert not Notification.objects.using("owner").exists()
    assert "dropped: 61 min late (max 60)" in caplog.text


def test_a_run_for_a_tenant_that_stopped_being_active_is_skipped(tenants: Any) -> None:
    tenants(wa_tenant(owner=OWNER, status="paused"))
    periodic.run_periodic(tenant("wa").id, "daily_summary", int(time.time()))
    assert not Notification.objects.using("owner").exists()


def test_dispatch_and_run_through_the_worker(tenants: Any) -> None:
    tenants(wa_tenant(owner=OWNER))
    app.configure_task(DISPATCH_PERIODIC, queue=PERIODIC).defer(
        timestamp=int(time.time()), pack="toy", name="daily_summary"
    )
    for _ in range(3):  # the dispatch queues the run, which a later pass may take
        run_jobs()
    assert Notification.objects.using("owner").count() == 1
    with connections["owner"].cursor() as cursor:
        cursor.execute(
            "SELECT task_name, status FROM procrastinate_jobs WHERE queue_name = 'periodic'"
        )
        statuses = dict(cursor.fetchall())
    assert statuses == {"dispatch_periodic": "succeeded", "run_periodic": "succeeded"}
