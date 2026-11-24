"""Every operation row uses PostgreSQL, simulated services and safe alert identities."""

import json
import os
from dataclasses import replace
from datetime import timedelta
from io import StringIO
from pathlib import Path
from typing import Any
from uuid import uuid7

import httpx
import pytest
from django.core.cache import cache
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import OperationalError, connection, connections
from django.utils import timezone

from autobot.ops import check, health, state, system
from autobot.ops.models import OpsAlert, SystemSample
from autobot.runtime.jobs import app
from autobot.runtime.models import Contact, Notification, OutboundMessage
from autobot.tenancy.registry import get_registry
from autobot.tenancy.tx import tenant_tx
from core.pack import Periodic
from tests.helpers.disk import fake_disk, statvfs_for
from tests.helpers.integration import demo_tenant, tg_tenant, wa_tenant

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
    ("status", "age_min", "expected"),
    [
        ("failed", 0, True),
        ("failed", 25 * 60, False),  # an old failure must not alert forever
        ("unknown", 11, False),  # reconcile_unknown still has its turn (ADR-026)
        ("unknown", 20, False),
        ("unknown", 21, True),
        ("unknown", 25 * 60, False),  # same 24 h cutoff as a failed message
        ("sent", 60, False),
        ("expired", 60, False),  # a lapsed message is not a failure (ADR-024)
    ],
)
def test_outbound_row(
    tenants: Any, alerts: Any, monkeypatch: Any, status: str, age_min: int, expected: bool
) -> None:
    tenants(wa_tenant())
    now = timezone.now()
    monkeypatch.setattr(timezone, "now", lambda: now)
    row = message(status=status, unknown_at=now - timedelta(minutes=age_min))
    OutboundMessage.objects.using("owner").filter(id=row.id).update(
        created_at=now - timedelta(minutes=age_min)
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


@pytest.mark.parametrize(
    ("age_h", "sent_after", "expected"),
    [
        (1, False, True),
        (25, False, False),  # an old rejection must not alert forever
        (1, True, False),  # a later send went through: the credential works again
    ],
)
def test_auth_row_is_recent_and_unresolved(
    tenants: Any, alerts: Any, monkeypatch: Any, age_h: int, sent_after: bool, expected: bool
) -> None:
    tenants(wa_tenant())
    now = timezone.now()
    monkeypatch.setattr(timezone, "now", lambda: now)
    rejected = message(status="failed", last_error="auth: HTTP 401")
    OutboundMessage.objects.using("owner").filter(id=rejected.id).update(
        created_at=now - timedelta(hours=age_h)
    )
    if sent_after:
        message(status="sent", sent_at=now - timedelta(minutes=5))
    check.run()
    assert ("auth" in kinds(alerts)) == expected


def test_every_tenant_alert_names_its_tenant(
    tenants: Any, alerts: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The operator reads the alert in Telegram: without the slug there is no way to
    # tell which business it is about (an `auth` alert once went out without it).
    tenants(wa_tenant())
    monkeypatch.setattr(
        health, "tenant_health", lambda tenant: [health.Issue("templates", "Faltan", "🟠")]
    )
    message(status="failed", last_error="auth: HTTP 401")
    check.run()
    tenant_alerts = [(kind, text) for kind, tenant_id, text in alerts if tenant_id is not None]
    assert {"auth", "outbound_failed", "health:templates"} <= {k for k, _ in tenant_alerts}
    assert all(text.startswith("wa: ") for _, text in tenant_alerts), tenant_alerts


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


def test_provider_outage_is_one_alert_that_resolves_itself(
    tenants: Any, alerts: Any, settings: Any, monkeypatch: Any
) -> None:
    """The breaker's signal becomes one `provider_outage` finding (not one per message),
    and it disappears when the breaker closes or the signal goes stale."""
    tenants(wa_tenant())
    state.record_provider("whatsapp", is_open=True)
    state.record_provider("telegram", is_open=True)
    findings = [f for f in check.collect() if f.kind == "provider_outage"]
    assert len(findings) == 1 and findings[0].tenant_id is None
    assert "telegram, whatsapp" in findings[0].text

    state.record_provider("telegram", is_open=False)
    state.record_provider("whatsapp", is_open=False)
    assert not [f for f in check.collect() if f.kind == "provider_outage"]

    state.record_provider("whatsapp", is_open=True)
    later = timezone.now() + state.PROVIDER_STALE_AFTER + timedelta(seconds=1)
    assert state.providers_down(later) == []  # a worker that died with it open


def test_provider_outage_alert_is_raised_once_and_auto_resolved(settings: Any) -> None:
    settings.OPS_TELEGRAM_CHAT_ID = ""
    settings.NOTIFY_BOT_TOKEN = ""
    finding = check.Finding("provider_outage", None, "🟠 Proveedor de mensajería caído (whatsapp)")
    check.sync_alerts([finding])
    check.sync_alerts([finding])
    (row,) = OpsAlert.objects.using("owner").filter(kind="provider_outage")
    assert row.resolved_at is None
    check.sync_alerts([])
    row.refresh_from_db(using="owner")
    assert row.resolved_by == "auto"


def test_disk_row(tenants: Any, alerts: Any, monkeypatch: Any) -> None:
    tenants()
    fake_disk(monkeypatch, 86)
    check.run()
    assert "disk" in kinds(alerts)


def test_disk_warning_starts_above_80_percent(tenants: Any, alerts: Any, monkeypatch: Any) -> None:
    tenants()
    fake_disk(monkeypatch, 81)
    check.run()
    assert "disk" in kinds(alerts)
    alerts.clear()
    fake_disk(monkeypatch, 80)
    check.run()
    assert "disk" not in kinds(alerts)


def test_the_fullest_measured_path_counts(
    tenants: Any, alerts: Any, monkeypatch: Any, settings: Any, tmp_path: Path
) -> None:
    """`/` and the ops state dir (the bind mount of /srv/autobot/var/state/ops)."""
    tenants()
    settings.OPS_STATE_DIR = tmp_path
    usage = {"/": 10, str(tmp_path): 96}
    monkeypatch.setattr(os, "statvfs", lambda path: statvfs_for(usage[str(path)])(path))
    check.run()
    assert "disk_critical" in kinds(alerts)


def test_disk_critical_row(tenants: Any, alerts: Any, monkeypatch: Any) -> None:
    tenants()
    fake_disk(monkeypatch, 96)
    check.run()
    assert "disk_critical" in kinds(alerts)
    assert "disk" not in kinds(alerts)


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


def test_daily_health_row_retries_a_failure_at_15_min(
    tenants: Any, alerts: Any, monkeypatch: Any
) -> None:
    """A one-off health failure must not stay cached a full day; it is rechecked
    at ~15 min, so it clears once the service is back."""
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
    monkeypatch.setattr(timezone, "now", lambda: now + timedelta(minutes=14))
    check.run()
    assert len(calls) == 1
    monkeypatch.setattr(timezone, "now", lambda: now + timedelta(minutes=16))
    check.run()
    assert len(calls) == 2


def test_daily_health_row_caches_a_success_for_a_day(
    tenants: Any, alerts: Any, monkeypatch: Any
) -> None:
    tenants(wa_tenant())
    calls = []

    def ok_health(tenant: Any) -> list[health.Issue]:
        calls.append(tenant.id)
        return []

    monkeypatch.setattr(health, "tenant_health", ok_health)
    now = timezone.now()
    monkeypatch.setattr(timezone, "now", lambda: now)
    check.run()
    monkeypatch.setattr(timezone, "now", lambda: now + timedelta(minutes=16))
    check.run()
    assert len(calls) == 1
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


def test_a_failing_tenant_does_not_abort_the_check_nor_the_heartbeat(
    tenants: Any, alerts: Any, settings: Any, monkeypatch: Any
) -> None:
    tenants(wa_tenant(), tg_tenant())
    settings.HEALTHCHECKS_PING_URL = "https://heartbeat.invalid/private"
    seen: list[Any] = []

    def ping(*args: Any, **kwargs: Any) -> httpx.Response:
        seen.append(args)
        return httpx.Response(200)

    monkeypatch.setattr(httpx, "get", ping)
    broken = get_registry().by_slug["wa"]
    checked: list[str] = []
    real_read = state.read

    def read(tenant_id: Any, channel: str) -> dict[str, Any]:
        if tenant_id == broken.id:
            raise RuntimeError("boom with +34600000000")
        checked.append(channel)
        return real_read(tenant_id, channel)

    monkeypatch.setattr(state, "read", read)
    check.run()
    failed = [a for a in alerts if a[0] == "check_failed"]
    assert [a[1] for a in failed] == [broken.id]
    assert checked  # the other tenant was still checked
    assert len(seen) == 1  # and the heartbeat was sent


def test_a_failed_tenant_check_keeps_its_open_alerts(tenants: Any, alerts: Any) -> None:
    tenants(wa_tenant())
    tenant = get_registry().by_slug["wa"]
    stale = OpsAlert.objects.using("owner").create(
        kind="errors:main", tenant_id=tenant.id, severity="critical", text="x", auto_resolves=True
    )
    check.sync_alerts([check.Finding(check.CHECK_FAILED, tenant.id, "x")])
    stale.refresh_from_db(using="owner")
    assert stale.resolved_at is None


def test_run_saves_a_system_sample_and_purges_old_ones(tenants: Any, alerts: Any) -> None:
    tenants()
    old = SystemSample.objects.using("owner").create(
        taken_at=timezone.now() - timedelta(days=63), db_bytes=1
    )
    check.run()
    assert not SystemSample.objects.using("owner").filter(id=old.id).exists()
    sample = SystemSample.objects.using("owner").latest("taken_at")
    assert sample.db_bytes > 0


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


@pytest.mark.parametrize("queue", ["inbound", "inbound_ext"])
@pytest.mark.parametrize(
    ("age", "future", "expected"), [(3, False, True), (2, False, False), (3, True, False)]
)
def test_inbound_immediate_and_future_jobs(
    tenants: Any, alerts: Any, monkeypatch: Any, age: int, future: bool, expected: bool, queue: str
) -> None:
    tenants()
    now = timezone.now()
    monkeypatch.setattr(timezone, "now", lambda: now)
    with connections["owner"].cursor() as cursor:
        cursor.execute(
            """INSERT INTO procrastinate_jobs(task_name, queue_name, status, args, scheduled_at)
            VALUES ('test', %s, 'todo', '{}', %s) RETURNING id""",
            [queue, now + timedelta(hours=1) if future else None],
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
    monkeypatch.setattr(timezone, "now", lambda: now + timedelta(minutes=21))
    check.run()
    assert "outbound_failed" in kinds(alerts)


def held_notice(slug: str = "wa") -> None:
    tenant = get_registry().by_slug[slug]
    with tenant_tx(tenant.id):
        Notification.objects.create(
            tenant_id=tenant.id, idem_key="held", kind="booking", text="x", status="held"
        )


def test_held_notices_raise_owner_unlinked_not_notification_failed(
    tenants: Any, alerts: Any
) -> None:
    tenants(wa_tenant())
    held_notice()
    check.run()
    assert "owner_unlinked" in kinds(alerts)
    assert "notification_failed" not in kinds(alerts)


def test_owner_unlinked_ignores_demo_tenants(tenants: Any, alerts: Any) -> None:
    tenants(demo_tenant())
    held_notice("demo-toy")
    check.run()
    assert "owner_unlinked" not in kinds(alerts)


@pytest.mark.parametrize("bot", ["demo_tg", "demo_wa", "notify"])
def test_platform_bot_auth_signal(tenants: Any, alerts: Any, bot: str) -> None:
    tenants()
    cache.set(f"bot:{bot}:auth", True, timeout=None)
    check.run()
    kind = f"auth:{bot}" if bot != "notify" else "bot:notify:auth"
    assert (kind, None) in [(a[0], a[1]) for a in alerts]


def test_notify_bot_webhook_unregistered_is_a_finding(
    tenants: Any, settings: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    # a demo/notify bot whose webhook Telegram has set to something else (or
    # nothing) must surface as a finding, not look "ok".
    tenants()
    settings.HEALTHCHECKS_PING_URL = ""
    settings.DEMO_TELEGRAM_TOKEN = ""
    settings.NOTIFY_BOT_TOKEN = "123:tok"
    settings.PUBLIC_URL = "https://api.example.org"

    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": True, "result": {"url": "https://old.example/x"}})

    original = httpx.Client
    monkeypatch.setattr(
        httpx, "Client", lambda **kwargs: original(transport=httpx.MockTransport(handle), **kwargs)
    )
    findings = check.collect()
    assert any(f.kind == "bot:notify:telegram_webhook_unregistered" for f in findings)


def test_collect_never_calls_send_ops_alert(tenants: Any, settings: Any, monkeypatch: Any) -> None:
    settings.HEALTHCHECKS_PING_URL = ""
    settings.DEMO_TELEGRAM_TOKEN = ""
    settings.NOTIFY_BOT_TOKEN = ""
    tenants(wa_tenant())
    monkeypatch.setattr(check, "door", lambda channel: None)
    monkeypatch.setattr(health, "tenant_health", lambda tenant: [])
    monkeypatch.setattr(system, "disk", lambda *_: 10.0)  # not the host's real disk
    for host_metric in ("inodes", "memory", "load", "swap"):
        monkeypatch.setattr(system, host_metric, lambda *_: 10.0)

    def boom(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("collect() must not send alerts")

    monkeypatch.setattr(check, "send_ops_alert", boom)
    findings = check.collect()
    assert findings == []


def test_sync_alerts_auto_resolves_a_disappeared_finding(settings: Any) -> None:
    settings.OPS_TELEGRAM_CHAT_ID = ""
    settings.NOTIFY_BOT_TOKEN = ""
    check.sync_alerts([check.Finding("stuck", None, "🔴 Algo falla")])
    row = OpsAlert.objects.using("owner").get(kind="stuck", tenant_id=None)
    assert row.resolved_at is None
    check.sync_alerts([])
    row.refresh_from_db(using="owner")
    assert row.resolved_at is not None and row.resolved_by == "auto"


def test_sync_alerts_notifies_only_a_disappeared_critical_finding(
    settings: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from autobot.runtime.notifications import resolve_alert as original_resolve_alert

    settings.OPS_TELEGRAM_CHAT_ID = ""
    settings.NOTIFY_BOT_TOKEN = ""
    notified: list[bool] = []

    def spy(alert: Any, *, by: str, notify: bool = False) -> None:
        notified.append(notify)
        original_resolve_alert(alert, by=by, notify=notify)

    monkeypatch.setattr(check, "resolve_alert", spy)
    check.sync_alerts([check.Finding("stuck", None, "🔴 Algo falla")])
    check.sync_alerts([check.Finding("billing", None, "🟡 Algo menor")])
    check.sync_alerts([])
    assert notified == [True, False]  # the critical one notifies, the minor one does not


def test_sync_alerts_never_auto_resolves_a_manual_kind(settings: Any) -> None:
    settings.OPS_TELEGRAM_CHAT_ID = ""
    settings.NOTIFY_BOT_TOKEN = ""
    check.sync_alerts([check.Finding("deploy_aborted", None, "🔴 Despliegue abortado")])
    check.sync_alerts([])
    row = OpsAlert.objects.using("owner").get(kind="deploy_aborted", tenant_id=None)
    assert row.resolved_at is None


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
    monkeypatch.setattr(
        "integrations.google_calendar.client.thread_service", lambda path: (service, None)
    )
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


def _write_containers_snapshot(state_dir: Path, *, missing_service: str | None = None) -> None:
    from autobot.ops.containers import EXPECTED_SERVICES

    state_dir.mkdir(parents=True, exist_ok=True)
    containers = [
        {
            "name": f"autobot-{service}-1",
            "service": service,
            "status": "running",
            "health": "healthy" if service != "db" else "none",
            "restart_count": 0,
            "oom_killed": False,
            "exit_code": 0,
            "started_at": "2026-11-11T09:00:00Z",
            "finished_at": None,
            "image": "ghcr.io/owner/autobot:abc123",
        }
        for service in EXPECTED_SERVICES
        if service != missing_service
    ]
    (state_dir / "containers.json").write_text(
        json.dumps(
            {
                "version": 1,
                "generated_at": timezone.now().isoformat(),
                "project": "autobot",
                "maintenance": None,
                "containers": containers,
            }
        )
    )


def test_container_findings_are_platform_wide_and_only_checked_off_local(
    tenants: Any, alerts: Any, settings: Any, tmp_path: Path
) -> None:
    tenants()
    settings.OPS_STATE_DIR = tmp_path
    settings.IS_LOCAL = True
    _write_containers_snapshot(tmp_path, missing_service="caddy")
    check.run()
    assert "container_down:caddy" not in kinds(alerts)  # skipped entirely in local

    alerts.clear()
    settings.IS_LOCAL = False
    check.run()
    assert ("container_down:caddy", None) in [(a[0], a[1]) for a in alerts]


def _write_prune_status(state_dir: Path, **fields: Any) -> None:
    (state_dir / "backup-prune.json").write_text(json.dumps(fields))


def test_backup_prune_overdue_raises_and_resolves(
    tenants: Any, alerts: Any, settings: Any, tmp_path: Path
) -> None:
    tenants()
    settings.OPS_STATE_DIR = tmp_path
    settings.IS_LOCAL = False
    now = timezone.now()
    _write_containers_snapshot(tmp_path)
    _write_prune_status(
        tmp_path,
        last_prune_at=(now - timedelta(days=11)).isoformat(),
        oldest_snapshot_at=(now - timedelta(days=100)).isoformat(),
    )
    check.run()
    assert "backup_prune_overdue" in kinds(alerts)

    alerts.clear()
    _write_prune_status(tmp_path, last_prune_at=(now - timedelta(days=2)).isoformat())
    check.run()
    assert "backup_prune_overdue" not in kinds(alerts)


def test_backup_prune_never_done_falls_back_to_the_oldest_snapshot(
    tenants: Any, alerts: Any, settings: Any, tmp_path: Path
) -> None:
    tenants()
    settings.OPS_STATE_DIR = tmp_path
    settings.IS_LOCAL = False
    now = timezone.now()
    _write_containers_snapshot(tmp_path)
    _write_prune_status(
        tmp_path, last_prune_at=None, oldest_snapshot_at=(now - timedelta(days=3)).isoformat()
    )
    check.run()
    assert "backup_prune_overdue" not in kinds(alerts)  # a young repository
    _write_prune_status(
        tmp_path, last_prune_at=None, oldest_snapshot_at=(now - timedelta(days=30)).isoformat()
    )
    check.run()
    assert "backup_prune_overdue" in kinds(alerts)


def test_backup_prune_without_a_state_file_or_in_local_does_not_alert(
    tenants: Any, alerts: Any, settings: Any, tmp_path: Path
) -> None:
    tenants()
    settings.OPS_STATE_DIR = tmp_path
    settings.IS_LOCAL = False
    _write_containers_snapshot(tmp_path)
    check.run()
    assert "backup_prune_overdue" not in kinds(alerts)
    _write_prune_status(tmp_path, last_prune_at="2020-01-01T00:00:00+00:00")
    settings.IS_LOCAL = True
    check.run()
    assert "backup_prune_overdue" not in kinds(alerts)


def test_sync_alerts_resolves_a_container_finding_once_the_service_is_back(
    settings: Any,
) -> None:
    settings.OPS_TELEGRAM_CHAT_ID = ""
    settings.NOTIFY_BOT_TOKEN = ""
    check.sync_alerts(
        [check.Finding("container_down:caddy", None, "🔴 Contenedor caddy: no existe.")]
    )
    row = OpsAlert.objects.using("owner").get(kind="container_down:caddy", tenant_id=None)
    assert row.resolved_at is None
    check.sync_alerts([])
    row.refresh_from_db(using="owner")
    assert row.resolved_at is not None and row.resolved_by == "auto"


def test_record_calendar_skips_the_write_when_nothing_changed(
    tenants: Any, monkeypatch: Any
) -> None:
    """Writing (and its advisory lock) is only worth it when the state actually
    changes: repeated "ok" observations (the overwhelming majority) must not write
    to the cache again and again."""
    tenants(wa_tenant())
    tenant_id = get_registry().by_slug["wa"].id
    writes: list[Any] = []
    original_set = cache.set

    def tracked(*args: Any, **kwargs: Any) -> None:
        writes.append(args[0])
        return original_set(*args, **kwargs)

    monkeypatch.setattr(cache, "set", tracked)
    state.record_calendar(tenant_id, "main", "ok")
    assert len(writes) == 1  # first observation: establishes the baseline
    state.record_calendar(tenant_id, "main", "ok")
    state.record_calendar(tenant_id, "main", "ok")
    assert len(writes) == 1  # no change: no further writes
    state.record_calendar(tenant_id, "main", "denied")
    assert len(writes) == 2  # a real change: written
    state.record_calendar(tenant_id, "main", "ok")
    assert len(writes) == 3  # recovered: written
    state.record_calendar(tenant_id, "main", "ok")
    assert len(writes) == 3  # already recovered: no change, no write


@pytest.mark.django_db(databases=["default", "owner"])
def test_audit_record_strips_nul_characters() -> None:
    from autobot.ops import audit
    from autobot.ops.models import AuditEvent

    audit.record(
        actor="a\x00b",
        action="x.y",
        summary="uno\x00dos",
        details={"k\x00": ["v\x00", {"n": "m\x00"}]},
    )
    event = AuditEvent.objects.using("owner").get(action="x.y")
    assert (event.actor, event.summary) == ("ab", "unodos")
    assert event.details == {"k": ["v", {"n": "m"}]}
