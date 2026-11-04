"""System endpoint against fake host files and patched external health checks."""

import json
import time
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest
from django.core.cache import cache
from django.db import connections

from autobot.ops.models import SystemSample
from autobot.panel.services.system import tls_days_left
from tests.integration.panel.conftest import get

pytestmark = pytest.mark.django_db(transaction=True, databases=["default", "owner"])
NOW = datetime(2026, 11, 4, 12, tzinfo=UTC)


@pytest.fixture(autouse=True)
def clean_workers() -> Iterator[None]:
    # Procrastinate's unmanaged tables are excluded from Django's test flush.
    with connections["owner"].cursor() as db:
        db.execute("DELETE FROM procrastinate_workers")
    yield
    with connections["owner"].cursor() as db:
        db.execute("DELETE FROM procrastinate_workers")


@pytest.mark.usefixtures("clean_jobs")
def test_system_endpoint(
    authed_client: Any, tmp_path: Path, settings: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from autobot.ops import system as host
    from autobot.ops.actions import queue_app

    settings.OPS_STATE_DIR = tmp_path
    settings.PUBLIC_URL = ""
    settings.RELEASE_SHA = "abc123"
    settings.VICTORIALOGS_URL = "http://logs.test"
    monkeypatch.setattr(host, "PROC", tmp_path)
    (tmp_path / "stat").write_text("cpu 100 0 100 700 0 0 0 0\n")
    (tmp_path / "meminfo").write_text("MemTotal: 1000 kB\nMemAvailable: 250 kB\n")
    (tmp_path / "loadavg").write_text("0.5 1 2\n")
    (tmp_path / "uptime").write_text("123 1\n")
    monkeypatch.setattr(
        time, "sleep", lambda _: (tmp_path / "stat").write_text("cpu 200 0 200 800 0 0 0 0\n")
    )
    monkeypatch.setattr(host, "disk", lambda: 42.0)
    seen = []

    def health(url: str, **kwargs: Any) -> httpx.Response:
        seen.append((url, kwargs))
        return httpx.Response(200)

    monkeypatch.setattr("autobot.panel.services.system.httpx.get", health)
    (tmp_path / "backup.json").write_text(
        json.dumps(
            {"finished_at": (NOW - timedelta(hours=9)).isoformat(), "ok": True, "dump_bytes": 100}
        )
    )
    (tmp_path / "deploys.jsonl").write_text('{"sha":"old"}\ninvalid\n{"sha":"new"}\n')
    for at in (NOW - timedelta(days=5), NOW - timedelta(hours=1), NOW + timedelta(hours=1)):
        SystemSample.objects.using("owner").create(taken_at=at, db_bytes=100)
    job = queue_app().configure_task("ops_check", queue="ops").defer()
    with connections["owner"].cursor() as db:
        db.execute(
            "UPDATE procrastinate_events SET at=%s WHERE job_id=%s AND type='deferred'",
            [NOW - timedelta(minutes=3), job],
        )
        db.execute(
            "INSERT INTO procrastinate_workers(last_heartbeat) VALUES (%s)",
            [NOW - timedelta(seconds=61)],
        )
    with patch("autobot.panel.services.system.timezone.now", return_value=NOW):
        response = get(authed_client, "system")
    assert response.status_code == 200, response.content
    data = response.json()
    assert data["machine"]["cpu_pct"] == pytest.approx(200 / 3)
    assert data["machine"]["mem_used_pct"] == 75
    assert data["machine"]["load1"] == 0.5
    assert data["machine"]["uptime_s"] == 123
    assert data["machine"]["disk_used_pct"] == 42
    assert len(data["samples"]) == 1
    assert data["backup"]["stale"]
    assert data["services"] == dict(web=True, worker=False, db=True, victorialogs=True)
    assert data["database"]["bytes"] > 0 and len(data["database"]["tables"]) == 5
    assert data["queues"] == [
        {
            "queue_name": "ops",
            "pending": 1,
            "oldest": (NOW - timedelta(minutes=3)).isoformat().replace("+00:00", "Z"),
            "age_s": 180,
        }
    ]
    assert [row["sha"] for row in data["deploys"]] == ["new", "old"]
    assert data["release"] == "abc123"
    assert seen == [("http://logs.test/health", {"timeout": 5})]
    with connections["owner"].cursor() as db:
        db.execute(
            "UPDATE procrastinate_workers SET last_heartbeat=%s", [NOW - timedelta(seconds=59)]
        )
    (tmp_path / "backup.json").write_text(
        json.dumps({"finished_at": (NOW - timedelta(hours=8)).isoformat(), "ok": True})
    )
    with patch("autobot.panel.services.system.timezone.now", return_value=NOW):
        data = get(authed_client, "system").json()
    assert data["services"]["worker"] and not data["backup"]["stale"]


@pytest.mark.parametrize("failed", [False, True])
def test_tls_cached_for_hour(settings: Any, failed: bool) -> None:
    settings.PUBLIC_URL = "https://public.test/some/path"
    cache.delete("panel:tls:public.test")
    context = MagicMock()
    context.wrap_socket.return_value.__enter__.return_value.getpeercert.return_value = {
        "notAfter": "Nov 14 12:00:00 2026 GMT"
    }
    with (
        patch("autobot.panel.services.system.ssl.create_default_context", return_value=context),
        patch("autobot.panel.services.system.socket.create_connection") as connect,
        patch("autobot.panel.services.system.timezone.now", return_value=NOW),
        patch("autobot.panel.services.system.cache.set", wraps=cache.set) as store,
    ):
        if failed:
            connect.side_effect = OSError("unavailable")
        assert tls_days_left() == (None if failed else 10)
        assert tls_days_left() == (None if failed else 10)
        connect.assert_called_once_with(("public.test", 443), timeout=5)
        assert store.call_args.kwargs["timeout"] == 3600
        if not failed:
            assert context.wrap_socket.call_args.kwargs["server_hostname"] == "public.test"
    cache.delete("panel:tls:public.test")


@pytest.mark.usefixtures("clean_jobs")
def test_missing_host_state_and_unreachable_logs(
    authed_client: Any, tmp_path: Path, settings: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from autobot.ops import system as host

    settings.OPS_STATE_DIR = tmp_path
    settings.PUBLIC_URL = ""
    settings.VICTORIALOGS_URL = "http://logs.test"
    monkeypatch.setattr(host, "PROC", tmp_path)
    monkeypatch.setattr(host, "disk", lambda: None)

    def unavailable(*args: Any, **kwargs: Any) -> Any:
        raise httpx.ConnectError("unavailable")

    monkeypatch.setattr("autobot.panel.services.system.httpx.get", unavailable)
    response = get(authed_client, "system")
    assert response.status_code == 200
    data = response.json()
    assert all(value is None for value in data["machine"].values())
    assert data["backup"] == {"stale": True}
    assert data["deploys"] == [] and data["queues"] == []
    assert not data["services"]["worker"] and not data["services"]["victorialogs"]
    assert data["tls"]["days_left"] is None


def test_overview_uses_shared_tls_check(monkeypatch: pytest.MonkeyPatch) -> None:
    from autobot.panel.services.overview import build_overview

    monkeypatch.setattr("autobot.panel.services.overview.tls_days_left", lambda: 17)
    assert build_overview(NOW).system.tls_days_left == 17
