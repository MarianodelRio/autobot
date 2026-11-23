"""A provider-wide outage is one alert, not one per tenant; the daily health checks are
spread and bounded per run."""

import shutil
from dataclasses import replace
from datetime import timedelta
from typing import Any
from uuid import UUID

import pytest
from django.utils import timezone

from autobot.ops import check, health, state
from autobot.ops.models import OpsAlert
from autobot.tenancy.registry import LoadedTenant, get_registry
from tests.helpers.integration import wa_tenant

pytestmark = [
    pytest.mark.django_db(transaction=True, databases=["default", "owner"]),
    pytest.mark.usefixtures("clean_jobs"),
]

N = 10


@pytest.fixture
def fleet(tenants: Any, monkeypatch: pytest.MonkeyPatch, settings: Any) -> list[LoadedTenant]:
    settings.HEALTHCHECKS_PING_URL = ""
    settings.DEMO_TELEGRAM_TOKEN = ""
    settings.NOTIFY_BOT_TOKEN = ""
    settings.OPS_TELEGRAM_CHAT_ID = ""
    monkeypatch.setattr(
        shutil, "disk_usage", lambda _: type("Disk", (), {"used": 1, "total": 100})()
    )
    tenants(*(wa_tenant(f"t{i}") for i in range(N)))
    fleet = list(get_registry().tenants)
    for tenant in fleet:
        assert tenant.pack
        object.__setattr__(tenant, "pack", replace(tenant.pack, needs_calendar=True))
    return fleet


def finding(kind: str, tenant: LoadedTenant) -> check.Finding:
    return check.Finding(kind, tenant.id, f"{tenant.slug}: x")


def run_suppression(
    findings: list[check.Finding], fleet: list[LoadedTenant]
) -> list[check.Finding]:
    return check._suppress_outages(findings, fleet, timezone.now())


# ── Google ───────────────────────────────────────────────────────────────


def test_a_few_broken_calendars_alert_one_by_one(fleet: list[LoadedTenant]) -> None:
    findings = [finding("calendar:main", t) for t in fleet[:2]]
    out = run_suppression(findings, fleet)
    assert not any(f.suppressed for f in out)
    assert check.CALENDAR_OUTAGE not in {f.kind for f in out}


def test_many_broken_calendars_are_one_platform_alert(fleet: list[LoadedTenant]) -> None:
    findings = [
        *(finding("calendar:main", t) for t in fleet[:4]),
        *(finding("health:main:calendar_unavailable", t) for t in fleet[3:7]),
        finding("errors:main", fleet[8]),
        finding("tenant_silent", fleet[9]),  # nothing to do with Google
    ]
    out = run_suppression(findings, fleet)
    per_tenant = {f.kind: f.suppressed for f in out if f.tenant_id}
    assert per_tenant["calendar:main"] and per_tenant["health:main:calendar_unavailable"]
    assert per_tenant["errors:main"] and not per_tenant["tenant_silent"]
    (outage,) = [f for f in out if f.kind == check.CALENDAR_OUTAGE]
    assert outage.tenant_id is None and not outage.suppressed and "7 de 10" in outage.text


def test_the_outage_replaces_open_tenant_alerts_without_paging(
    fleet: list[LoadedTenant], monkeypatch: pytest.MonkeyPatch, settings: Any
) -> None:
    paged: list[str] = []
    monkeypatch.setattr("autobot.ops.check.send_ops_alert", lambda *a: None)

    def resolve(alert: OpsAlert, *, by: str, notify: bool = False) -> None:
        if notify:
            paged.append(alert.kind)
        OpsAlert.objects.using("owner").filter(id=alert.id).update(resolved_by=by)

    monkeypatch.setattr("autobot.ops.check.resolve_alert", resolve)
    for t in fleet[:6]:
        OpsAlert.objects.using("owner").create(
            kind="calendar:main",
            tenant_id=t.id,
            severity="critical",
            text="🔴 x",
            first_seen_at=timezone.now(),
            last_seen_at=timezone.now(),
        )
    findings = [finding("calendar:main", t) for t in fleet[:6]]
    check.sync_alerts(run_suppression(findings, fleet))
    rows = OpsAlert.objects.using("owner").filter(kind="calendar:main")
    assert {r.resolved_by for r in rows} == {"outage"} and paged == []


def test_a_tenant_alert_that_ends_with_the_outage_is_not_paged_either(
    fleet: list[LoadedTenant], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The calendars recover together: their findings vanish while `calendar_outage` is
    still open (or just closed), and their critical alerts resolve silently."""
    paged: list[str] = []
    monkeypatch.setattr("autobot.ops.check.send_ops_alert", lambda *a: None)

    def resolve(alert: OpsAlert, *, by: str, notify: bool = False) -> None:
        if notify:
            paged.append(alert.kind)

    monkeypatch.setattr("autobot.ops.check.resolve_alert", resolve)
    now = timezone.now()
    OpsAlert.objects.using("owner").create(
        kind=check.CALENDAR_OUTAGE,
        severity="critical",
        text="🔴 x",
        first_seen_at=now,
        last_seen_at=now,
    )
    OpsAlert.objects.using("owner").create(
        kind="calendar:main",
        tenant_id=fleet[0].id,
        severity="critical",
        text="🔴 x",
        first_seen_at=now,
        last_seen_at=now,
    )
    check.sync_alerts([])
    # Only the platform alert tells the operator it is over.
    assert paged == [check.CALENDAR_OUTAGE]


# ── Meta / Telegram ──────────────────────────────────────────────────────


def test_a_meta_outage_holds_back_the_tenants_unavailable_alerts(
    fleet: list[LoadedTenant],
) -> None:
    findings = [finding("health:whatsapp_unavailable", t) for t in fleet]
    findings.append(finding("health:telegram_unavailable", fleet[0]))
    assert not any(f.suppressed for f in run_suppression(findings, fleet))  # no outage

    state.record_provider("whatsapp", is_open=True)
    out = run_suppression(findings, fleet)
    assert all(f.suppressed for f in out if f.kind == "health:whatsapp_unavailable")
    assert not [f for f in out if f.kind == "health:telegram_unavailable" and f.suppressed]

    state.record_provider("whatsapp", is_open=False)  # recovered: still held for the grace
    out = run_suppression(findings, fleet)
    assert all(f.suppressed for f in out if f.kind == "health:whatsapp_unavailable")
    late = timezone.now() + check.OUTAGE_GRACE + timedelta(minutes=1)
    assert state.providers_recovering(late, check.OUTAGE_GRACE) == []


# ── Health checks: spread and budget ─────────────────────────────────────


def test_offsets_are_stable_and_spread_the_day() -> None:
    names = [UUID(int=i * 7919 + 1) for i in range(200)]
    offsets = [health.spread_s(n) for n in names]
    assert offsets == [health.spread_s(n) for n in names]
    assert all(0 <= o < health.SPREAD_WINDOW_S for o in offsets)
    assert len({o // 600 for o in offsets}) >= 10  # across the window, not bunched
    assert all(health.success_ttl_s(n) < health.DAY_S for n in names)


def test_a_failed_check_is_still_retried_after_fifteen_minutes() -> None:
    now = timezone.now()
    name = UUID(int=5)
    failed = health.HealthSnapshot(now - timedelta(minutes=16), [health.Issue("x", "m")])
    fresh = health.HealthSnapshot(now - timedelta(minutes=16), [])
    assert health.overdue_s(name, failed, now) > 0 > health.overdue_s(name, fresh, now)
    assert health.overdue_s(name, None, now) > health.overdue_s(name, failed, now)


def test_a_cold_start_checks_at_most_the_budget_per_run_and_everyone_in_the_end(
    fleet: list[LoadedTenant], monkeypatch: pytest.MonkeyPatch, alerts_off: None
) -> None:
    clock = {"t": 0.0}
    monkeypatch.setattr(health, "_monotonic", lambda: clock["t"])
    monkeypatch.setattr(check, "HEALTH_BUDGET_S", 6.0)
    checked: list[UUID] = []

    def slow_health(tenant: LoadedTenant) -> list[health.Issue]:
        clock["t"] += 2.0  # each external check takes 2 s
        checked.append(tenant.id)
        return []

    monkeypatch.setattr(health, "tenant_health", slow_health)
    per_run = []
    for _ in range(N):
        before = len(checked)
        check.collect()
        per_run.append(len(checked) - before)
        if len(checked) >= N:
            break
    assert max(per_run) <= 3 and per_run[0] == 3  # 6 s budget / 2 s each
    assert sorted(checked) == sorted(t.id for t in fleet)  # all of them, once each
    before = len(checked)
    check.collect()
    assert len(checked) == before  # nothing due again until tomorrow


@pytest.fixture
def alerts_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(check, "send_ops_alert", lambda *a: None)
