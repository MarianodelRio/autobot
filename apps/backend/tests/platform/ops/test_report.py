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


def test_open_alerts_most_severe_and_recent_first() -> None:
    now = timezone.now()
    for kind, severity, age in [
        ("a", "warning", 1),
        ("b", "critical", 5),
        ("c", "critical", 1),
        ("d", "info", 0),
    ]:
        OpsAlert.objects.create(
            kind=kind, severity=severity, text=kind, first_seen_at=now - timedelta(hours=age)
        )
    OpsAlert.objects.create(kind="e", severity="critical", text="e", resolved_at=now)
    assert [a.text for a in report.open_alerts()] == ["c", "b", "a", "d"]


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
    with connections["owner"].cursor() as cursor:
        cursor.execute(
            "INSERT INTO procrastinate_jobs (queue_name, task_name, status, args, scheduled_at)"
            " VALUES ('periodic', 'retention_cleanup', 'failed', '{}', %s)",
            [now - timedelta(hours=8)],
        )
    OpsAlert.objects.create(kind="disk", severity="warning", text="🟠 Disco")
    status = report.platform_status(now)
    assert status.level == "warning"
    assert status.resources is not None and status.resources.disk_pct == 40.0
    assert status.backups.ok is True and status.backups.stale  # more than 3 hours ago
    assert status.cleanup.ok is False


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
