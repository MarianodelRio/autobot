"""`ops.report` against the real database (ADR-029): a day's figures read tenant by tenant
under RLS, as the worker does, and the platform's state from its tables and files."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid7

import pytest
from django.db import connections
from django.utils import timezone
from pytest_django import Settings

from autobot.ops import report
from autobot.ops.models import OpsAlert, SystemSample
from autobot.runtime.models import Contact, InboundEvent, OutboundMessage
from autobot.tenancy.registry import get_registry
from tests.helpers.integration import demo_tenant, wa_tenant

pytestmark = [
    pytest.mark.django_db(transaction=True, databases=["default", "owner"]),
    pytest.mark.usefixtures("clean_jobs"),
]

MADRID = report.MADRID


def contact(slug: str, external_id: str, created_at: datetime) -> Contact:
    tenant = get_registry().by_slug[slug]
    row = Contact.objects.using("owner").create(
        tenant_id=tenant.id, channel="main", external_id=external_id
    )
    Contact.objects.using("owner").filter(id=row.id).update(created_at=created_at)
    return row


def received(slug: str, at: datetime, kind: str = "message") -> None:
    tenant = get_registry().by_slug[slug]
    InboundEvent.objects.using("owner").create(
        tenant_id=tenant.id,
        channel="main",
        kind=kind,
        provider_event_id=str(uuid7()),
        status="done",
        received_at=at,
    )


def sent(slug: str, to: Contact, at: datetime, status: str = "sent") -> None:
    tenant = get_registry().by_slug[slug]
    row = OutboundMessage.objects.using("owner").create(
        tenant_id=tenant.id,
        contact=to,
        idem_key=str(uuid7()),
        channel="main",
        kind="reply",
        status=status,
        sent_at=at if status == "sent" else None,
    )
    OutboundMessage.objects.using("owner").filter(id=row.id).update(created_at=at)


def test_day_bounds_are_madrid_midnights_even_across_dst() -> None:
    now = datetime(2026, 10, 26, 10, 0, tzinfo=MADRID)  # the day after the change to winter
    assert report.day_bounds(now) == (datetime(2026, 10, 26, tzinfo=MADRID), now)
    start, end = report.day_bounds(now, days_ago=1)
    assert (start, end) == (
        datetime(2026, 10, 25, tzinfo=MADRID),
        datetime(2026, 10, 26, tzinfo=MADRID),
    )
    # Same-zone subtraction is wall-clock; the real length of that day is 25 hours.
    assert end.astimezone(UTC) - start.astimezone(UTC) == timedelta(hours=25)


def test_a_day_counts_each_tenant_inside_its_own_rls(tenants: Any) -> None:
    tenants(wa_tenant("wa"), wa_tenant("otro"), demo_tenant("demo-toy"))
    start, end = report.day_bounds(timezone.now())
    inside, before = start + timedelta(minutes=1), start - timedelta(minutes=1)
    lucia = contact("wa", "34600000001", inside)
    contact("wa", "34600000002", before)  # yesterday: not new today
    received("wa", inside)
    received("wa", inside)
    received("wa", inside, kind="status")  # a delivery status is not a message
    received("wa", before)
    sent("wa", lucia, inside)
    sent("wa", lucia, inside, status="failed")
    sent("wa", lucia, inside, status="expired")  # a lapsed reply is not a failure (ADR-024)
    sent("wa", lucia, inside, status="discarded")  # a person's decision (ADR-031)
    demo = contact("demo-toy", "100000001", before)
    received("demo-toy", inside)
    sent("demo-toy", demo, inside)

    day = report.day_figures(start, end)
    by_name = {t.name: t for t in day.tenants}
    assert by_name["Wa"].figures == report.Figures(received=2, sent=1, failed=1, new_contacts=1)
    assert by_name["Otro"].figures.empty
    assert [t.name for t in day.real] == ["Wa"]  # the quiet tenant is left out
    assert day.demos == report.Figures(received=1, sent=1)
    assert day.total == report.Figures(received=3, sent=2, failed=1, new_contacts=1)


def test_open_incidents_most_severe_and_recent_first() -> None:
    now = timezone.now()
    for kind, severity, age in [
        ("a", "warning", 1),
        ("b", "critical", 5),
        ("c", "critical", 1),
        ("f", "notice", 2),
        ("d", "info", 0),
    ]:
        OpsAlert.objects.create(
            kind=kind,
            severity=severity,
            text=kind,
            first_seen_at=now - timedelta(hours=age),
            last_seen_at=now - timedelta(hours=age),
        )
    OpsAlert.objects.create(kind="e", severity="critical", text="e", resolved_at=now)
    assert [a.text for a in report.open_incidents()] == ["c", "b", "a", "f", "d"]


def test_a_reopened_event_carries_its_new_cases() -> None:
    now = timezone.now()
    kind = "failed_job:ops_check"
    OpsAlert.objects.create(
        kind=kind,
        severity="warning",
        text="old",
        auto_resolves=False,
        resolved_at=now,
        resolved_by="ana",
        review_watermark=now,
    )
    OpsAlert.objects.create(
        kind=kind, severity="warning", text="new", auto_resolves=False, case_count=2
    )
    OpsAlert.objects.create(
        kind="deploy_aborted", severity="critical", text="d", auto_resolves=False, case_count=1
    )
    lines = {line.text: line for line in report.open_incidents()}
    assert lines["new"].new_since_review == 2
    assert lines["d"].new_since_review is None  # never reviewed: nothing to compare with


def test_platform_status_from_its_tables_and_files(
    tenants: Any, settings: Settings, tmp_path: Path
) -> None:
    tenants(wa_tenant("wa"))
    settings.OPS_STATE_DIR = tmp_path
    now = timezone.now()
    status = report.platform_status(now)
    # Nothing recorded yet: said as such, never as a failure.
    assert status.level == "ok"
    assert (status.services, status.resources) == (None, None)
    assert status.backups == report.Backups(None, None, False, None, False)
    assert (status.cleanup.last_at, status.cleanup.ok) == (None, None)

    SystemSample.objects.create(disk_used_pct=40.0, mem_used_pct=60.0, db_bytes=2048)
    (tmp_path / "backup.json").write_text(
        json.dumps({"finished_at": (now - timedelta(hours=4)).isoformat(), "ok": True})
    )
    failed_at = now - timedelta(hours=8)
    with connections["owner"].cursor() as cursor:
        # As a periodic job is: no scheduled_at; its time is in its events.
        cursor.execute(
            "INSERT INTO procrastinate_jobs (queue_name, task_name, status, args)"
            " VALUES ('periodic', 'retention_cleanup', 'failed', '{}') RETURNING id"
        )
        (job_id,) = cursor.fetchone()
        cursor.execute(
            "INSERT INTO procrastinate_events (job_id, type, at) VALUES (%s, 'failed', %s)",
            [job_id, failed_at],
        )
    OpsAlert.objects.create(kind="disk", severity="warning", text="🟠 Disco")
    status = report.platform_status(now)
    assert status.level == "warning"
    assert status.resources is not None and status.resources.disk_pct == 40.0
    assert status.backups.ok is True and status.backups.stale  # more than 3 hours ago
    assert status.cleanup == report.Cleanup(
        enabled=settings.RETENTION_CLEANUP_ENABLED, last_at=failed_at, ok=False
    )


def _nightly_cleanup(status: str) -> int:
    """A retention_cleanup job deferred exactly as Procrastinate's periodic deferrer does
    (its SQL function, so without scheduled_at), then moved through its statuses so the
    triggers write the real events."""
    with connections["owner"].cursor() as cursor:
        cursor.execute(
            "SELECT procrastinate_defer_periodic_job_v2("
            "'periodic', NULL, 'retention_cleanup', 'retention_cleanup', 0,"
            " 'retention_cleanup', %s, %s::jsonb)",
            [int(timezone.now().timestamp()), json.dumps({"timestamp": 0})],
        )
        (job_id,) = cursor.fetchone()
        for step in ("doing", status) if status != "todo" else ():
            cursor.execute(
                "UPDATE procrastinate_jobs SET status = %s WHERE id = %s", [step, job_id]
            )
    return job_id


def _age_events(job_id: int, by: timedelta) -> None:
    with connections["owner"].cursor() as cursor:
        cursor.execute(
            "UPDATE procrastinate_events SET at = at - %s WHERE job_id = %s", [by, job_id]
        )


@pytest.mark.parametrize(
    ("status", "ok"), [("succeeded", True), ("failed", False), ("doing", None)]
)
def test_cleanup_reads_a_real_periodic_job(
    settings: Settings, status: str, ok: bool | None
) -> None:
    settings.RETENTION_CLEANUP_ENABLED = True
    job_id = _nightly_cleanup(status)
    with connections["owner"].cursor() as cursor:
        cursor.execute("SELECT scheduled_at FROM procrastinate_jobs WHERE id = %s", [job_id])
        assert cursor.fetchone() == (None,)  # what hid every run before
    _age_events(job_id, timedelta(hours=5))
    now = timezone.now()
    cleanup = report.cleanup(now)
    assert cleanup.ok is ok and not cleanup.stale
    assert cleanup.last_at is not None
    assert timedelta(hours=5) <= now - cleanup.last_at < timedelta(hours=5, minutes=1)


def test_cleanup_is_stale_after_a_day_without_a_run(settings: Settings) -> None:
    settings.RETENTION_CLEANUP_ENABLED = True
    job_id = _nightly_cleanup("succeeded")
    _age_events(job_id, timedelta(hours=27))
    assert report.cleanup(timezone.now()).stale
    # Switched off on purpose: an old run is expected, not a warning.
    settings.RETENTION_CLEANUP_ENABLED = False
    assert not report.cleanup(timezone.now()).stale


def test_tenant_lines_carry_health_and_last_activity(tenants: Any) -> None:
    tenants(wa_tenant("wa"), wa_tenant("pausado", status="paused"))
    at = timezone.now() - timedelta(hours=2)
    received("wa", at)
    wa = get_registry().by_slug["wa"]
    OpsAlert.objects.create(kind="auth", severity="critical", text="🔴 wa", tenant_id=wa.id)
    lines = {line.slug: line for line in report.tenant_lines(timezone.now())}
    assert lines["wa"].last_activity_at == at
    assert lines["wa"].level == "critical" and lines["wa"].reasons
    assert lines["pausado"].status == "paused" and lines["pausado"].last_activity_at is None
    status = report.platform_status(timezone.now())
    assert status.level == "critical" and status.troubled == ["Wa"]
