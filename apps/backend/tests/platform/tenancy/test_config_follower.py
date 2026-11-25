"""`config_follower`: each process tells the database which configuration revision it has
loaded (ADR-030), throttled, never breaking the refresher; and the readers' view of it."""

import os
import socket
import threading
import time
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from django.db import OperationalError, connections

from autobot.tenancy import followers, registry
from autobot.tenancy.models import ConfigFollower, ConfigRevision
from tests.platform.tenancy.helpers import PACKS, tenant_document

NOW = datetime(2026, 11, 25, 12, tzinfo=UTC)


@pytest.fixture
def beat(monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    """A loaded registry at revision 1 with a fake clock and a recording heartbeat."""
    registry.reset_registry()
    state = SimpleNamespace(now=100.0, revision=1, writes=[])
    monkeypatch.setattr(registry, "time", SimpleNamespace(monotonic=lambda: state.now))
    monkeypatch.setattr("packs.registry.PACKS", PACKS)
    monkeypatch.setattr(registry, "_read_revision", lambda: state.revision)
    monkeypatch.setattr(
        registry,
        "sources_from_database",
        lambda alias="default": (
            state.revision,
            [registry.TenantSource("a", tenant_document("a"), version=state.revision)],
        ),
    )
    monkeypatch.setattr(registry, "_write_beat", lambda revision: state.writes.append(revision))
    monkeypatch.setattr(registry, "_beat_revision", None)
    monkeypatch.setattr(registry, "_beat_at", float("-inf"))
    monkeypatch.setattr(registry, "_beat_retry_at", float("-inf"))
    registry.get_registry()
    yield state
    registry.stop_polling()
    assert not [t for t in threading.enumerate() if t.name == "registry-refresh"], "leaked"
    registry.reset_registry()


def test_the_first_beat_writes_and_the_next_ones_wait_for_the_interval(beat: Any) -> None:
    registry._beat(beat.now)
    assert beat.writes == [1]
    for _ in range(5):  # polls every 2 s: nothing to say
        beat.now += 2
        registry._beat(beat.now)
    assert beat.writes == [1]
    beat.now += registry.HEARTBEAT_SECONDS
    registry._beat(beat.now)
    assert beat.writes == [1, 1]  # alive, same revision


def test_a_revision_change_is_written_at_once(beat: Any) -> None:
    registry._beat(beat.now)
    beat.revision = 2
    beat.now += 2
    registry.get_registry(force=True)
    registry._beat(beat.now)
    assert beat.writes == [1, 2]


def test_nothing_is_written_before_the_registry_is_loaded(beat: Any) -> None:
    registry.reset_registry()
    registry._beat(beat.now)
    assert beat.writes == []


def test_a_failed_beat_is_swallowed_and_retried_after_the_interval(
    beat: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = []

    def boom(revision: int) -> None:
        calls.append(revision)
        raise OperationalError("private database details")

    monkeypatch.setattr(registry, "_write_beat", boom)
    registry._beat(beat.now)  # must not raise
    beat.now += 2
    registry._beat(beat.now)  # inside the retry window: not even tried
    assert calls == [1]
    beat.now += registry.HEARTBEAT_SECONDS
    registry._beat(beat.now)
    assert calls == [1, 1]


def test_a_failing_heartbeat_does_not_stop_the_refresher_following_the_revision(
    beat: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(revision: int) -> None:
        raise OperationalError("down")

    monkeypatch.setattr(registry, "_write_beat", boom)
    registry.start_polling(0.02)
    beat.revision = 2
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        loaded = registry.loaded_registry()
        if loaded is not None and loaded.tenants[0].version == 2:
            break
        time.sleep(0.01)
    loaded = registry.loaded_registry()
    assert loaded is not None and loaded.tenants[0].version == 2


def test_a_polling_process_beats_and_a_lazy_one_does_not(beat: Any) -> None:
    beat.now += 2
    registry.get_registry()  # lazy: wakes the refresher, no polling
    registry.wait_for_refresh()
    assert beat.writes == []
    registry.start_polling(0.02)
    deadline = time.monotonic() + 5
    while not beat.writes and time.monotonic() < deadline:
        time.sleep(0.01)
    assert beat.writes == [1]


# ── the real upsert and the readers ────────────────────────────────────────────────


@pytest.mark.django_db(transaction=True, databases=["default", "owner"])
def test_the_real_beat_upserts_one_row_per_process(settings: Any) -> None:
    settings.SERVICE_NAME = "worker-x"
    registry._write_beat(4)
    registry._write_beat(5)
    row = ConfigFollower.objects.get()
    assert (row.service, row.host, row.pid, row.revision) == (
        "worker-x",
        socket.gethostname(),
        os.getpid(),
        5,
    )
    assert row.seen_at >= row.started_at


@pytest.mark.django_db(transaction=True, databases=["default", "owner"])
def test_stopping_the_refresher_removes_the_row(monkeypatch: pytest.MonkeyPatch) -> None:
    registry.reset_registry()
    monkeypatch.setattr(registry, "_beat_revision", None)
    monkeypatch.setattr(registry, "_beat_at", float("-inf"))
    ConfigRevision.objects.using("owner").get_or_create(pk=1)
    monkeypatch.setattr("packs.registry.PACKS", PACKS)
    monkeypatch.setattr(registry, "_read_revision", lambda: 1)
    monkeypatch.setattr(
        registry,
        "sources_from_database",
        lambda alias="default": (1, [registry.TenantSource("a", tenant_document("a"), version=1)]),
    )
    registry.get_registry()
    registry._beat(time.monotonic() + 1000)
    assert ConfigFollower.objects.count() == 1
    registry.start_polling(0.02)
    registry.stop_polling()
    assert ConfigFollower.objects.count() == 0
    connections.close_all()
    registry.reset_registry()


@pytest.mark.django_db(transaction=True, databases=["default", "owner"])
def test_read_state_marks_only_alive_processes_and_the_ones_behind() -> None:
    ConfigRevision.objects.using("owner").update_or_create(pk=1, defaults={"revision": 7})

    def row(pid: int, service: str, revision: int, age_s: int) -> None:
        ConfigFollower.objects.create(
            service=service,
            host="h",
            pid=pid,
            revision=revision,
            started_at=NOW - timedelta(hours=1),
            seen_at=NOW - timedelta(seconds=age_s),
        )

    row(1, "web", 7, 5)
    row(2, "worker-inbound", 6, 20)  # behind
    row(3, "web-panel", 3, followers.ALIVE_SECONDS + 1)  # dead: ignored
    state = followers.read_state(NOW)
    assert state.revision == 7
    assert [(f.service, f.behind) for f in state.followers] == [
        ("web", False),
        ("worker-inbound", True),
    ]
    assert followers.read_state(NOW, alias="owner").followers == state.followers


@pytest.mark.django_db(transaction=True, databases=["default", "owner"])
def test_purge_stale_deletes_only_rows_not_seen_for_a_day() -> None:
    for pid, age in ((1, timedelta(hours=2)), (2, timedelta(days=2))):
        ConfigFollower.objects.create(
            service="web", host="h", pid=pid, revision=1, started_at=NOW - age, seen_at=NOW - age
        )
    assert followers.purge_stale(NOW) == 1
    assert list(ConfigFollower.objects.values_list("pid", flat=True)) == [1]
