"""Every operation row uses PostgreSQL, simulated services and safe alert identities."""

import shutil
from dataclasses import replace
from datetime import timedelta
from io import StringIO
from typing import Any
from uuid import uuid7

import httpx
import pytest
from django.core.cache import cache
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import OperationalError, connection, connections
from django.utils import timezone

from autobot.jobs import app
from autobot.ops import check, health, state
from autobot.runtime.models import Contact, OutboundMessage
from autobot.tenancy.registry import get_registry
from autobot.tenancy.tx import tenant_tx
from core.pack import Periodic
from tests.integration.helpers import wa_tenant

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
    monkeypatch.setattr(
        shutil, "disk_usage", lambda _: type("Disk", (), {"used": 1, "total": 100})()
    )
    return found


def message(**fields: Any) -> OutboundMessage:
    tenant = get_registry().by_slug["wa"]
    with tenant_tx(tenant.id):
        contact, _ = Contact.objects.get_or_create(
            tenant_id=tenant.id, channel="main", external_id="ES.test"
        )
        return OutboundMessage.objects.create(
            tenant_id=tenant.id,
            contact=contact,
            idem_key=str(uuid7()),
            channel="main",
            kind="reply",
            **fields,
        )


def kinds(alerts: list[tuple[Any, ...]]) -> set[str]:
    return {a[0] for a in alerts}


@pytest.mark.parametrize(
    ("status", "age", "expected"),
    [("failed", 0, True), ("unknown", 11, True), ("unknown", 10, False), ("sent", 60, False)],
)
def test_outbound_row(
    tenants: Any, alerts: Any, monkeypatch: Any, status: str, age: int, expected: bool
) -> None:
    tenants(wa_tenant())
    now = timezone.now()
    monkeypatch.setattr(timezone, "now", lambda: now)
    row = message(status=status, unknown_at=now - timedelta(minutes=age))
    OutboundMessage.objects.using("owner").filter(id=row.id).update(
        created_at=now - timedelta(days=2)
    )
    check.run()
    assert ("outbound_failed" in kinds(alerts)) == expected


def test_auth_row_separates_the_demo_bot(tenants: Any, alerts: Any) -> None:
    tenants(wa_tenant())
    row = message(status="failed", last_error="auth: HTTP 401")
    check.run()
    assert ("auth", row.tenant_id) in [(a[0], a[1]) for a in alerts]
    alerts.clear()
    OutboundMessage.objects.using("owner").filter(id=row.id).update(channel="demo_tg")
    check.run()
    assert ("auth:demo_tg", None) in [(a[0], a[1]) for a in alerts]
    assert "auth" not in kinds(alerts)


@pytest.mark.parametrize("degraded", [True, False])
def test_unavailable_row(tenants: Any, alerts: Any, degraded: bool) -> None:
    tenants(wa_tenant(config={"colors": 1}) if degraded else wa_tenant(), secrets={})
    check.run()
    assert "tenant_unavailable" in kinds(alerts)


def test_three_errors_reset_and_persist(tenants: Any, alerts: Any) -> None:
    tenants(wa_tenant())
    tenant = get_registry().by_slug["wa"]
    for _ in range(3):
        state.record(tenant.id, "main", failed=True)
    check.run()
    assert "errors:main" in kinds(alerts)
    assert state.read(tenant.id, "demo_tg") == {}
    state.record(tenant.id, "main", failed=False)
    alerts.clear()
    check.run()
    assert "errors:main" not in kinds(alerts)


def test_sweep_completion_baseline_and_stale_row(
    tenants: Any, alerts: Any, monkeypatch: Any
) -> None:
    tenants(wa_tenant())
    tenant = get_registry().by_slug["wa"]
    assert tenant.pack
    object.__setattr__(
        tenant,
        "pack",
        replace(tenant.pack, periodic=[Periodic("calendar_sweep", 15, lambda ctx: [], 60)]),
    )
    now = timezone.now()
    state.sweep_baseline(tenant.id, "main", now - timedelta(hours=2))
    check.run()
    assert "sweep:main" in kinds(alerts)
    state.record(tenant.id, "main", failed=False, sweep=True)
    alerts.clear()
    check.run()
    assert "sweep:main" not in kinds(alerts)
    assert state.read(tenant.id, "main")["last_sweep"]


@pytest.mark.parametrize("count", [1, 2])
def test_billable_row(tenants: Any, alerts: Any, count: int) -> None:
    doc = wa_tenant()
    doc["channel"]["monthly_alert_threshold"] = 1
    tenants(doc)
    for _ in range(count):
        message(status="sent", billable=True, sent_at=timezone.now())
    message(status="sent", billable=True, sent_at=timezone.now() - timedelta(days=40))
    check.run()
    assert ("billing" in kinds(alerts)) == (count > 1)


def test_disk_row(tenants: Any, alerts: Any, monkeypatch: Any) -> None:
    tenants()
    monkeypatch.setattr(
        shutil, "disk_usage", lambda _: type("Disk", (), {"used": 86, "total": 100})()
    )
    check.run()
    assert "disk" in kinds(alerts)


def test_queue_rows(tenants: Any, alerts: Any) -> None:
    tenants()
    with connections["owner"].cursor() as cursor:
        cursor.execute(
            """INSERT INTO procrastinate_jobs(task_name, queue_name, status, args, scheduled_at)
            VALUES ('test', 'inbound', 'todo', '{}', %s) RETURNING id""",
            [timezone.now() - timedelta(minutes=3)],
        )
        cursor.execute(
            """INSERT INTO procrastinate_jobs(task_name, queue_name, status, args)
            VALUES ('test', 'inbound', 'failed', '{}') RETURNING id"""
        )
        (job_id,) = cursor.fetchone()
        cursor.execute(
            "INSERT INTO procrastinate_events(job_id, type, at) VALUES (%s, 'failed', %s)",
            [job_id, timezone.now()],
        )
    check.run()
    assert {"inbound_delay", "failed_jobs"} <= kinds(alerts)


def test_daily_health_row_caches_failures_and_refreshes(
    tenants: Any, alerts: Any, monkeypatch: Any
) -> None:
    tenants(wa_tenant())
    calls = []

    def failed_health(tenant: Any) -> list[health.Issue]:
        calls.append(tenant.id)
        return [health.Issue("main:calendar_unavailable", "Calendar inaccesible.", "🔴")]

    monkeypatch.setattr(health, "tenant_health", failed_health)
    now = timezone.now()
    monkeypatch.setattr(timezone, "now", lambda: now)
    check.run()
    check.run()
    assert len(calls) == 1
    assert "health:main:calendar_unavailable" in kinds(alerts)
    monkeypatch.setattr(timezone, "now", lambda: now + timedelta(days=1))
    check.run()
    assert len(calls) == 2


def test_heartbeat_only_after_success(
    tenants: Any, alerts: Any, settings: Any, monkeypatch: Any
) -> None:
    tenants()
    settings.HEALTHCHECKS_PING_URL = "https://heartbeat.invalid/private"
    seen = []

    def heartbeat(*args: Any, **kwargs: Any) -> httpx.Response:
        seen.append(args)
        return httpx.Response(200)

    monkeypatch.setattr(httpx, "get", heartbeat)
    check.run()
    assert len(seen) == 1
    monkeypatch.setattr(
        connection, "cursor", lambda: (_ for _ in ()).throw(OperationalError("db down"))
    )
    with pytest.raises(OperationalError):
        check.run()
    assert len(seen) == 1


def test_registration() -> None:
    task = app.periodic_registry.periodic_tasks[("ops_check", "ops_check")]
    assert task.cron == "*/5 * * * *"


def test_command_success_and_failure(tenants: Any, monkeypatch: Any) -> None:
    tenants(wa_tenant())
    monkeypatch.setattr(
        "autobot.management.commands.tenant_health.tenant_health", lambda tenant: []
    )
    output = StringIO()
    call_command("tenant_health", "wa", stdout=output)
    assert "Salud correcta" in output.getvalue()
    with pytest.raises(CommandError, match="desconocido"):
        call_command("tenant_health", "missing")
    monkeypatch.setattr(
        "autobot.management.commands.tenant_health.tenant_health",
        lambda tenant: [health.Issue("x", "Problema")],
    )
    with pytest.raises(CommandError, match="problemas"):
        call_command("tenant_health", "wa", stdout=StringIO())


@pytest.mark.parametrize(
    ("age", "future", "expected"), [(3, False, True), (2, False, False), (3, True, False)]
)
def test_inbound_immediate_and_future_jobs(
    tenants: Any, alerts: Any, monkeypatch: Any, age: int, future: bool, expected: bool
) -> None:
    tenants()
    now = timezone.now()
    monkeypatch.setattr(timezone, "now", lambda: now)
    with connections["owner"].cursor() as cursor:
        cursor.execute(
            """INSERT INTO procrastinate_jobs(task_name, queue_name, status, args, scheduled_at)
            VALUES ('test', 'inbound', 'todo', '{}', %s) RETURNING id""",
            [now + timedelta(hours=1) if future else None],
        )
        (job_id,) = cursor.fetchone()
        cursor.execute(
            "UPDATE procrastinate_events SET at = %s WHERE job_id = %s AND type = 'deferred'",
            [now - timedelta(minutes=age), job_id],
        )
    check.run()
    assert ("inbound_delay" in kinds(alerts)) == expected


def test_unknown_legacy_first_observation(tenants: Any, alerts: Any, monkeypatch: Any) -> None:
    tenants(wa_tenant())
    now = timezone.now()
    monkeypatch.setattr(timezone, "now", lambda: now)
    row = message(status="unknown")
    OutboundMessage.objects.using("owner").filter(id=row.id).update(
        created_at=now - timedelta(days=2)
    )
    check.run()
    assert "outbound_failed" not in kinds(alerts)
    assert OutboundMessage.objects.using("owner").get(id=row.id).unknown_at == now
    monkeypatch.setattr(timezone, "now", lambda: now + timedelta(minutes=11))
    check.run()
    assert "outbound_failed" in kinds(alerts)


@pytest.mark.parametrize("bot", ["demo_tg", "demo_wa", "notify"])
def test_platform_bot_auth_signal(tenants: Any, alerts: Any, bot: str) -> None:
    tenants()
    cache.set(f"bot:{bot}:auth", True, timeout=None)
    check.run()
    kind = f"auth:{bot}" if bot != "notify" else "bot:notify:auth"
    assert (kind, None) in [(a[0], a[1]) for a in alerts]


def test_calendar_denial_is_detected_even_after_healthy_daily_check(
    tenants: Any, alerts: Any, monkeypatch: Any
) -> None:
    from contextlib import suppress
    from unittest.mock import Mock

    import httplib2  # type: ignore[import-untyped]
    from googleapiclient.errors import HttpError  # type: ignore[import-untyped]
    from pydantic import BaseModel

    from autobot.runtime.context import build_context
    from autobot.runtime.models import Channel
    from integrations.google_calendar.client import CalendarPermanentError

    class CalendarConfig(BaseModel):
        calendar_id: str = "simulated-calendar"

    tenants(wa_tenant())
    tenant = get_registry().by_slug["wa"]
    assert tenant.pack
    object.__setattr__(tenant, "pack", replace(tenant.pack, needs_calendar=True))
    object.__setattr__(tenant, "config", CalendarConfig())
    service = Mock()
    service.events.return_value.list.return_value.execute.side_effect = HttpError(
        httplib2.Response({"status": "403"}), b'{"error":{"message":"private"}}'
    )
    monkeypatch.setattr("integrations.google_calendar.client.service", lambda path: service)
    health.daily(tenant.id, lambda: [])
    ctx = build_context(tenant, Channel.MAIN, contact=None, state={}, event_id=None)
    # The pack may catch this exception and return a normal recovery response.
    with suppress(CalendarPermanentError):
        ctx.calendar.check_access()
    state.record(tenant.id, "main", failed=False)
    check.run()
    assert "calendar:main" in kinds(alerts)
    service.events.return_value.list.return_value.execute.side_effect = None
    service.events.return_value.list.return_value.execute.return_value = {"items": []}
    ctx.calendar.check_access()
    alerts.clear()
    check.run()
    assert "calendar:main" not in kinds(alerts)
