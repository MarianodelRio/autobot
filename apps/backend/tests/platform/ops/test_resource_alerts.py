"""Host pressure, inodes, backup freshness, TLS expiry, a broken alert channel, and the
other ops_check hardening checks, with PostgreSQL and simulated hosts."""

import json
import os
import ssl
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
import pytest
from django.db import DatabaseError
from django.utils import timezone

from autobot.ops import check, health, queues, system
from autobot.ops.models import OpsAlert, SystemSample
from autobot.owner import links
from autobot.runtime import notifications
from autobot.runtime.models import Notification
from autobot.tenancy.registry import get_registry
from autobot.tenancy.tx import tenant_tx
from tests.helpers.disk import fake_disk
from tests.helpers.integration import wa_tenant

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
    monkeypatch.setattr(check, "send_ops_alert", lambda *args, **_: found.append(args))
    monkeypatch.setattr(health, "tenant_health", lambda tenant: [])
    monkeypatch.setattr(system, "memory", lambda: 10.0)
    monkeypatch.setattr(system, "load", lambda: 0.1)
    monkeypatch.setattr(system, "swap", lambda: 0.0)
    fake_disk(monkeypatch, 1)
    return found


def kinds(alerts: list[tuple[Any, ...]]) -> set[str]:
    return {a[0] for a in alerts}


def sample(minutes_ago: float = 5, **fields: Any) -> None:
    SystemSample.objects.create(
        taken_at=timezone.now() - timedelta(minutes=minutes_ago), db_bytes=0, **fields
    )


# --- memory, load, swap ---------------------------------------------------------------


def test_memory_needs_two_consecutive_samples(
    tenants: Any, alerts: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    tenants()
    monkeypatch.setattr(system, "memory", lambda: 95.0)
    check.run()  # no previous sample: a spike, not a trend
    assert "memory_high" not in kinds(alerts)
    check.run()  # the first run stored a 95 % sample
    assert "memory_high" in kinds(alerts)


def test_memory_with_a_calm_previous_sample_is_not_sustained(
    tenants: Any, alerts: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    tenants()
    sample(mem_used_pct=50.0)
    monkeypatch.setattr(system, "memory", lambda: 95.0)
    check.run()
    assert "memory_high" not in kinds(alerts)


def test_a_stale_previous_sample_is_not_evidence(
    tenants: Any, alerts: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    tenants()
    sample(minutes_ago=120, mem_used_pct=99.0)
    monkeypatch.setattr(system, "memory", lambda: 95.0)
    check.run()
    assert "memory_high" not in kinds(alerts)


def test_load_is_relative_to_the_cpu_count(
    tenants: Any, alerts: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    tenants()
    monkeypatch.setattr(os, "cpu_count", lambda: 2)
    sample(load1=4.5)
    monkeypatch.setattr(system, "load", lambda: 3.9)  # below 2 x 2
    check.run()
    assert "load_high" not in kinds(alerts)
    SystemSample.objects.all().delete()
    sample(minutes_ago=1, load1=4.5)
    monkeypatch.setattr(system, "load", lambda: 4.5)
    check.run()
    assert "load_high" in kinds(alerts)


def test_swap_alert(tenants: Any, alerts: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    tenants()
    monkeypatch.setattr(system, "swap", lambda: 60.0)
    check.run()
    assert "swap_high" in kinds(alerts)


def test_unreadable_host_metrics_raise_nothing(
    tenants: Any, alerts: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    tenants()
    for name in ("memory", "load", "swap"):
        monkeypatch.setattr(system, name, lambda: None)
    check.run()
    assert not kinds(alerts) & {"memory_high", "load_high", "swap_high"}


# --- inodes ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("inodes_pct", "expected"),
    [(79, None), (85, "inodes"), (97, "inodes_critical")],
)
def test_inodes_thresholds(
    tenants: Any,
    alerts: Any,
    monkeypatch: pytest.MonkeyPatch,
    inodes_pct: int,
    expected: str | None,
) -> None:
    tenants()
    fake_disk(monkeypatch, 1, inodes_pct)
    check.run()
    assert kinds(alerts) & {"inodes", "inodes_critical"} == ({expected} if expected else set())


# --- backup freshness -----------------------------------------------------------------


def write_backup(tmp_path: Path, settings: Any, **fields: Any) -> None:
    settings.OPS_STATE_DIR = tmp_path
    (tmp_path / "backup.json").write_text(json.dumps(fields))


def stamp(delta: timedelta) -> str:
    return (datetime.now(UTC) - delta).strftime("%Y-%m-%dT%H:%M:%SZ")


def test_fresh_successful_backup_is_fine(tmp_path: Path, settings: Any) -> None:
    write_backup(tmp_path, settings, finished_at=stamp(timedelta(minutes=30)), ok=True)
    assert check._backup_findings(timezone.now()) == []


def test_old_backup_is_stale(tmp_path: Path, settings: Any) -> None:
    write_backup(tmp_path, settings, finished_at=stamp(timedelta(hours=4)), ok=True)
    assert [f.kind for f in check._backup_findings(timezone.now())] == ["backup_stale"]


def test_failed_last_backup_is_stale_even_if_recent(tmp_path: Path, settings: Any) -> None:
    write_backup(tmp_path, settings, finished_at=stamp(timedelta(minutes=5)), ok=False)
    assert [f.kind for f in check._backup_findings(timezone.now())] == ["backup_stale"]


def test_no_backup_file_yet_is_not_an_alert(tmp_path: Path, settings: Any) -> None:
    settings.OPS_STATE_DIR = tmp_path
    assert check._backup_findings(timezone.now()) == []


def test_unparseable_finish_time_is_stale(tmp_path: Path, settings: Any) -> None:
    write_backup(tmp_path, settings, finished_at="yesterday", ok=True)
    assert [f.kind for f in check._backup_findings(timezone.now())] == ["backup_stale"]


# --- TLS ------------------------------------------------------------------------------


def serve_cert(monkeypatch: pytest.MonkeyPatch, days: float) -> None:
    monkeypatch.setattr(
        health,
        "_cert_not_after",
        lambda host, port, timeout: datetime.now(UTC) + timedelta(days=days),
    )


@pytest.mark.parametrize(
    ("days", "expected"),
    [
        (40, []),
        (13, ["tls_expiring"]),
        (2, ["tls_expiring_critical"]),
        (-1, ["tls_expiring_critical"]),
    ],
)
def test_tls_days_left(monkeypatch: pytest.MonkeyPatch, days: float, expected: list[str]) -> None:
    serve_cert(monkeypatch, days)
    assert [i.code for i in health.tls_health("api.example.org")] == expected


def test_tls_invalid_certificate(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*args: Any) -> datetime:
        raise ssl.SSLCertVerificationError("expired")

    monkeypatch.setattr(health, "_cert_not_after", boom)
    assert [i.code for i in health.tls_health("api.example.org")] == ["tls_invalid"]


@pytest.mark.parametrize("error", [TimeoutError("slow"), OSError("refused"), ssl.SSLError("x")])
def test_tls_network_errors_never_raise(monkeypatch: pytest.MonkeyPatch, error: Exception) -> None:
    def boom(*args: Any) -> datetime:
        raise error

    monkeypatch.setattr(health, "_cert_not_after", boom)
    assert health.tls_health("api.example.org") == []


@pytest.mark.parametrize("url", ["", "http://localhost:8000", "https://abc.ngrok-free.app"])
def test_tls_is_skipped_without_a_public_host(
    settings: Any, monkeypatch: pytest.MonkeyPatch, url: str
) -> None:
    settings.PUBLIC_URL = url
    monkeypatch.setattr(health, "tls_health", lambda host: pytest.fail("must not connect"))
    assert check._tls_findings() == []


def test_tls_finding_is_cached_by_daily(settings: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    settings.PUBLIC_URL = "https://api.example.org"
    serve_cert(monkeypatch, 5)
    findings = check._tls_findings()
    assert [f.kind for f in findings] == ["tls_expiring"]


# --- the alert channel itself -----------------------------------------------------------


def open_alert(delivery: str, minutes_ago: float, severity: str = "critical") -> None:
    OpsAlert.objects.create(
        kind="registry",
        severity=severity,
        text="x",
        last_delivery=delivery,
        auto_resolves=False,  # stays open through ops_check's own sync, as a live one would
        first_seen_at=timezone.now() - timedelta(minutes=minutes_ago),
    )


def ping_urls(monkeypatch: pytest.MonkeyPatch, settings: Any) -> list[str]:
    settings.HEALTHCHECKS_PING_URL = "https://hc.invalid/ping/abc123"
    urls: list[str] = []

    def get(url: str, **kwargs: Any) -> httpx.Response:
        urls.append(url)
        return httpx.Response(200)

    monkeypatch.setattr(httpx, "get", get)
    return urls


@pytest.mark.parametrize("delivery", ["failed", "unconfigured"])
def test_undelivered_critical_alert_sends_the_fail_ping(
    tenants: Any, alerts: Any, settings: Any, monkeypatch: pytest.MonkeyPatch, delivery: str
) -> None:
    tenants()
    urls = ping_urls(monkeypatch, settings)
    open_alert(delivery, minutes_ago=20)
    check.run()
    assert urls == ["https://hc.invalid/ping/abc123/fail"]


@pytest.mark.parametrize(
    ("delivery", "minutes_ago", "severity"),
    [("sent", 60, "critical"), ("failed", 5, "critical"), ("failed", 60, "warning")],
)
def test_other_alerts_keep_the_success_ping(
    tenants: Any,
    alerts: Any,
    settings: Any,
    monkeypatch: pytest.MonkeyPatch,
    delivery: str,
    minutes_ago: float,
    severity: str,
) -> None:
    tenants()
    urls = ping_urls(monkeypatch, settings)
    open_alert(delivery, minutes_ago, severity)
    check.run()
    assert urls == ["https://hc.invalid/ping/abc123"]


def test_a_failed_delivery_survives_the_cooldown(settings: Any) -> None:
    settings.OPS_TELEGRAM_CHAT_ID = ""
    assert not notifications.send_ops_alert("stuck", None, "🔴 Algo falla")
    assert not notifications.send_ops_alert("stuck", None, "🔴 Algo falla otra vez")
    row = OpsAlert.objects.using("owner").get(kind="stuck")
    assert row.last_delivery == "unconfigured" and row.occurrences == 2


# --- owner_unlinked ---------------------------------------------------------------------


def notice(status: str, hours_ago: float = 3) -> None:
    tenant = get_registry().by_slug["wa"]
    with tenant_tx(tenant.id):
        row = Notification.objects.create(
            tenant_id=tenant.id, idem_key=str(uuid4()), kind="booking", text="x", status=status
        )
        Notification.objects.filter(id=row.id).update(
            created_at=timezone.now() - timedelta(hours=hours_ago)
        )


def test_expired_notices_keep_owner_unlinked_open(tenants: Any, alerts: Any) -> None:
    tenants(wa_tenant())
    notice("expired")  # expire_held already turned the held one into this
    check.run()
    assert "owner_unlinked" in kinds(alerts)


def test_old_expired_notices_do_not(tenants: Any, alerts: Any) -> None:
    tenants(wa_tenant())
    notice("expired", hours_ago=30)
    check.run()
    assert "owner_unlinked" not in kinds(alerts)


def test_a_linked_owner_is_not_unlinked(
    tenants: Any, alerts: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    tenants(wa_tenant())
    notice("held")
    monkeypatch.setattr(links, "owner_chat", lambda tenant_id: 123)
    check.run()
    assert "owner_unlinked" not in kinds(alerts)


# --- a Google outage and non-calendar tenants ---------------------------------------------


def test_google_outage_does_not_explain_errors_of_tenants_without_calendar() -> None:
    salon, bus = uuid4(), uuid4()
    scope = check.OutageScope(
        provider_kinds=frozenset(),
        google=True,
        google_down=True,
        affected=6,
        calendar_tenants=6,
        calendar_ids=frozenset({salon}),
    )
    assert scope.explains("errors:main", salon)
    assert not scope.explains("errors:main", bus)
    assert scope.explains("calendar:main", bus)  # a calendar signal is Google's by definition


# --- queue lag degradation ------------------------------------------------------------------


def test_a_failing_lag_query_degrades_to_a_finding(
    tenants: Any, alerts: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    tenants()

    def timeout(cursor: Any, now: Any) -> Any:
        raise DatabaseError("canceling statement due to statement timeout")

    monkeypatch.setattr(queues, "queue_lags", timeout)
    check.run()  # does not raise
    assert "queue_lag_unknown" in kinds(alerts)


# --- config_stale (ADR-030) --------------------------------------------------------------


def _follower(
    service: str,
    revision: int,
    *,
    seen_s_ago: int = 5,
    error_s_ago: int | None = None,
    pid: int = 1,
) -> None:
    from autobot.tenancy.models import ConfigFollower

    now = timezone.now()
    ConfigFollower.objects.create(
        service=service,
        host=service,
        pid=pid,
        revision=revision,
        started_at=now - timedelta(hours=1),
        seen_at=now - timedelta(seconds=seen_s_ago),
        last_error_at=None if error_s_ago is None else now - timedelta(seconds=error_s_ago),
    )


def _revision(value: int, changed_s_ago: int) -> None:
    from autobot.tenancy.models import ConfigRevision

    ConfigRevision.objects.using("owner").update_or_create(pk=1, defaults={"revision": value})
    # `updated_at` is auto_now: set it behind the ORM's back.
    ConfigRevision.objects.using("owner").filter(pk=1).update(
        updated_at=timezone.now() - timedelta(seconds=changed_s_ago)
    )


@pytest.fixture(autouse=True)
def _clean_cache() -> None:
    from django.core.cache import cache

    cache.clear()  # the first-seen marks live in the cache, which outlives a test's flush


def _config_kinds(now: Any) -> list[str]:
    return [f.kind for f in _findings_at(now)]


def _findings_at(now: Any) -> Any:
    """The findings as of `now`, the processes having written their rows just before."""
    from autobot.tenancy.models import ConfigFollower

    ConfigFollower.objects.update(seen_at=now - timedelta(seconds=2))
    return check._config_findings(now)


def test_config_stale_counts_a_minute_from_when_that_process_was_first_seen_behind(
    tenants: Any,
) -> None:
    tenants()
    _revision(9, changed_s_ago=3600)  # the revision is old: it is not what is measured
    _follower("web", 9)
    _follower("worker-outbound", 8)
    now = timezone.now()
    assert _config_kinds(now) == []  # first time seen behind: the minute starts now
    assert _config_kinds(now + timedelta(seconds=59)) == []
    (finding,) = _findings_at(now + timedelta(seconds=61))
    assert finding.kind == "config_stale" and finding.tenant_id is None
    assert "worker-outbound" in finding.text and "web," not in finding.text


def test_config_stale_does_not_restart_when_the_database_moves_again(tenants: Any) -> None:
    tenants()
    _revision(9, changed_s_ago=300)
    _follower("worker-inbound", 8)
    now = timezone.now()
    assert _config_kinds(now) == []
    _revision(10, changed_s_ago=1)  # another write: the process is still on revision 8
    assert _config_kinds(now + timedelta(seconds=90)) == ["config_stale"]


def test_config_stale_also_names_a_process_ahead_of_a_database_restored_to_an_older_revision(
    tenants: Any,
) -> None:
    tenants()
    _revision(5, changed_s_ago=10)
    _follower("web", 7)
    now = timezone.now()
    assert _config_kinds(now) == []
    assert _config_kinds(now + timedelta(seconds=70)) == ["config_stale"]


def test_config_stale_names_a_process_whose_checks_keep_failing(tenants: Any) -> None:
    tenants()
    _revision(9, changed_s_ago=3600)
    _follower("web", 9, error_s_ago=30)  # failing for 30 s: not yet
    _follower("worker-inbound", 9, error_s_ago=120, pid=2)
    (finding,) = _findings_at(timezone.now())
    assert "worker-inbound" in finding.text and "web," not in finding.text
    assert "fallan" in finding.text


def test_config_stale_ignores_dead_processes_and_ones_up_to_date(tenants: Any) -> None:
    tenants()
    _revision(9, changed_s_ago=600)
    _follower("web", 9)
    _follower("worker-inbound", 3, seen_s_ago=300, error_s_ago=900)  # gone: its row is old
    _follower("worker-outbound", 3, seen_s_ago=followers_alive() + 1, pid=3)
    now = timezone.now()
    assert check._config_findings(now) == []
    assert check._config_findings(now + timedelta(seconds=20)) == []  # `web` is current


def followers_alive() -> int:
    from autobot.tenancy import followers

    return followers.ALIVE_SECONDS


def test_config_stale_resolves_when_the_process_catches_up(
    tenants: Any, monkeypatch: pytest.MonkeyPatch, settings: Any
) -> None:
    from autobot.tenancy.models import ConfigFollower

    tenants()
    settings.HEALTHCHECKS_PING_URL = ""
    settings.DEMO_TELEGRAM_TOKEN = settings.NOTIFY_BOT_TOKEN = ""
    monkeypatch.setattr(health, "tenant_health", lambda tenant: [])
    monkeypatch.setattr(system, "memory", lambda: 10.0)
    monkeypatch.setattr(system, "load", lambda: 0.1)
    monkeypatch.setattr(system, "swap", lambda: 0.0)
    fake_disk(monkeypatch, 1)
    monkeypatch.setattr(notifications, "_send_text", lambda *a, **k: None, raising=False)
    _revision(9, changed_s_ago=120)
    _follower("web", 8, error_s_ago=300)
    check.sync_alerts(check.collect())
    assert OpsAlert.objects.filter(kind="config_stale", resolved_at__isnull=True).count() == 1
    ConfigFollower.objects.update(revision=9, last_error_at=None)
    check.sync_alerts(check.collect())
    assert OpsAlert.objects.filter(kind="config_stale", resolved_at__isnull=True).count() == 0


def test_the_check_purges_followers_not_seen_for_a_day(tenants: Any, alerts: Any) -> None:
    from autobot.tenancy.models import ConfigFollower

    tenants()
    _revision(1, changed_s_ago=10)
    _follower("old", 1, seen_s_ago=3 * 86400)
    _follower("web", 1)
    check.run()
    assert list(ConfigFollower.objects.values_list("service", flat=True)) == ["web"]
