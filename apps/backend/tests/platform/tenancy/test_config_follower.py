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
from tests.platform.tenancy.helpers import PACKS, reader_of, tenant_document

NOW = datetime(2026, 11, 25, 12, tzinfo=UTC)


@pytest.fixture
def beat(monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    """A loaded registry at revision 1 with a fake clock and a recording heartbeat."""
    registry.reset_registry()
    state = SimpleNamespace(now=100.0, revision=1, writes=[], errors=[])
    monkeypatch.setattr(registry, "time", SimpleNamespace(monotonic=lambda: state.now))
    monkeypatch.setattr("packs.registry.PACKS", PACKS)
    monkeypatch.setattr(registry, "_read_revision", lambda: state.revision)
    monkeypatch.setattr(
        registry,
        "_read_config",
        reader_of(
            lambda: (
                state.revision,
                [registry.TenantSource("a", tenant_document("a"), version=state.revision)],
            )
        ),
    )
    monkeypatch.setattr(
        registry,
        "_write_beat",
        lambda revision, error: (state.writes.append(revision), state.errors.append(error)),
    )
    monkeypatch.setattr(registry, "_beat_key", None)
    monkeypatch.setattr(registry, "_beat_at", float("-inf"))
    monkeypatch.setattr(registry, "_beat_retry_at", float("-inf"))
    monkeypatch.setattr(registry, "_error_since", None)
    registry._last_logged.clear()
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


def test_a_process_that_loaded_nothing_yet_still_beats_with_revision_zero(beat: Any) -> None:
    registry.reset_registry()
    registry._beat(beat.now)
    assert beat.writes == [0]


def test_a_failed_beat_is_swallowed_and_retried_after_the_interval(
    beat: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = []

    def boom(revision: int, error: Any) -> None:
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
    def boom(revision: int, error: Any) -> None:
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


def wait_until(condition: Any, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.01)
    return False


def test_every_polling_round_beats_even_when_the_check_fails_and_says_so(
    beat: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    def down() -> int:
        raise OperationalError("private database details")

    registry.start_polling(0.01)
    assert wait_until(lambda: beat.writes == [1])
    assert beat.errors == [None]
    monkeypatch.setattr(registry, "_read_revision", down)
    # The failure is reported at once, with the revision it still serves...
    assert wait_until(lambda: len(beat.writes) == 2)
    assert beat.writes == [1, 1] and beat.errors[1] is not None
    since = beat.errors[1]
    # ...and keeps being the start of the run, not the latest failure.
    beat.now += registry.HEARTBEAT_SECONDS
    assert wait_until(lambda: len(beat.writes) == 3)
    assert beat.errors[2] == since
    # Recovery clears it at once.
    monkeypatch.setattr(registry, "_read_revision", lambda: beat.revision)
    assert wait_until(lambda: len(beat.writes) == 4)
    assert beat.errors[3] is None


def test_a_first_load_that_keeps_failing_beats_revision_zero_and_logs_once(
    beat: Any, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    registry.reset_registry()

    def down(known: Any) -> Any:
        raise OperationalError("database down")

    calls = []

    def counting(known: Any) -> Any:
        calls.append(1)
        return down(known)

    monkeypatch.setattr(registry, "_read_config", counting)
    with caplog.at_level("WARNING", logger="autobot.tenancy.registry"):
        registry.start_polling(0.005)
        assert wait_until(lambda: len(calls) >= 20)
        registry.stop_polling()
    assert beat.writes[0] == 0 and beat.errors[0] is not None
    tracebacks = [r for r in caplog.records if r.exc_info]
    assert len(tracebacks) <= 2  # the refresher's first failure (and nothing every 5 ms)
    assert len(caplog.records) <= 4


def test_a_healthy_kept_connection_is_not_tested_every_round(
    beat: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    tested: list[Any] = []

    def usable() -> bool:
        tested.append(1)
        return True

    connection = SimpleNamespace(
        connection=object(),
        errors_occurred=True,
        is_usable=usable,
        close=lambda: tested.append("close"),
    )
    monkeypatch.setattr(registry, "connections", {"default": connection})
    registry._prepare_connection(True)
    registry._prepare_connection(True)
    registry._prepare_connection(True)
    assert tested == [1] and connection.errors_occurred is False


# ── the real upsert and the readers ────────────────────────────────────────────────


@pytest.mark.django_db(transaction=True, databases=["default", "owner"])
def test_the_real_beat_upserts_one_row_per_process(settings: Any) -> None:
    settings.SERVICE_NAME = "worker-x"
    registry._write_beat(4, None)
    registry._write_beat(5, None)
    row = ConfigFollower.objects.get()
    assert (row.service, row.host, row.pid, row.revision) == (
        "worker-x",
        socket.gethostname(),
        os.getpid(),
        5,
    )
    assert row.seen_at >= row.started_at
    assert row.last_error_at is None
    failed_since = datetime.now(UTC)
    registry._write_beat(5, failed_since)
    row.refresh_from_db()
    assert row.last_error_at == failed_since


@pytest.mark.django_db(transaction=True, databases=["default", "owner"])
def test_a_clean_exit_removes_the_row_on_its_own_bounded_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry._write_beat(3, None)
    assert ConfigFollower.objects.count() == 1
    monkeypatch.setattr(registry, "_beat_key", (3, False))
    registry._forget_process()  # what `atexit` runs
    assert ConfigFollower.objects.count() == 0
    registry._forget_process()  # nothing written any more: no work at all


def test_the_exit_hook_never_raises_nor_hangs_on_a_sick_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Down:
        def create_connection(self, alias: str) -> Any:
            raise OperationalError("down")

    monkeypatch.setattr(registry, "connections", Down())
    monkeypatch.setattr(registry, "_beat_key", (3, False))
    started = time.monotonic()
    registry._forget_process()
    assert time.monotonic() - started < 1


@pytest.mark.django_db(transaction=True, databases=["default", "owner"])
def test_stopping_the_refresher_removes_the_row(monkeypatch: pytest.MonkeyPatch) -> None:
    registry.reset_registry()
    monkeypatch.setattr(registry, "_beat_key", None)
    monkeypatch.setattr(registry, "_beat_at", float("-inf"))
    ConfigRevision.objects.using("owner").get_or_create(pk=1)
    monkeypatch.setattr("packs.registry.PACKS", PACKS)
    monkeypatch.setattr(registry, "_read_revision", lambda: 1)
    monkeypatch.setattr(
        registry,
        "_read_config",
        reader_of(lambda: (1, [registry.TenantSource("a", tenant_document("a"), version=1)])),
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
    # Another revision is behind too, also an older one in the database (a restore).
    ConfigRevision.objects.using("owner").filter(pk=1).update(revision=5)
    assert [(f.service, f.behind) for f in followers.read_state(NOW).followers] == [
        ("web", True),
        ("worker-inbound", True),
    ]
    ConfigRevision.objects.using("owner").filter(pk=1).update(revision=7)
    assert followers.read_state(NOW, alias="owner").followers == state.followers


@pytest.mark.django_db(transaction=True, databases=["default", "owner"])
def test_purge_stale_deletes_only_rows_not_seen_for_a_day() -> None:
    for pid, age in ((1, timedelta(hours=2)), (2, timedelta(days=2))):
        ConfigFollower.objects.create(
            service="web", host="h", pid=pid, revision=1, started_at=NOW - age, seen_at=NOW - age
        )
    assert followers.purge_stale(NOW) == 1
    assert list(ConfigFollower.objects.values_list("pid", flat=True)) == [1]
