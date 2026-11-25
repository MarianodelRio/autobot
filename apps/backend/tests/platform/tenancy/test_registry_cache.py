"""Revision polling and work scopes retain a consistent registry snapshot."""

import threading
import time
import uuid
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from typing import Any

import pytest
from django.db import OperationalError
from django.http import HttpRequest, HttpResponse

from autobot.ops.logging import contextual, redact
from autobot.tenancy import registry
from autobot.tenancy.middleware import RegistryScopeMiddleware
from tests.platform.tenancy.helpers import PACKS, reader_of, tenant_document


@pytest.fixture
def state(monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    registry.reset_registry()
    state = SimpleNamespace(now=10.0, revision=1, loads=0, beats=[])
    # The heartbeat (a `config_follower` upsert) is tested in test_config_follower.py.
    monkeypatch.setattr(
        registry, "_write_beat", lambda revision, error: state.beats.append(revision)
    )
    monkeypatch.setattr(registry, "time", SimpleNamespace(monotonic=lambda: state.now))
    monkeypatch.setattr("packs.registry.PACKS", PACKS)
    monkeypatch.setattr(registry, "_read_revision", lambda: state.revision)

    def sources(alias: str = "default") -> tuple[int, list[registry.TenantSource]]:
        state.loads += 1
        return state.revision, [
            registry.TenantSource("a", tenant_document("a"), version=state.revision)
        ]

    monkeypatch.setattr(registry, "_read_config", reader_of(sources))
    yield state
    registry.stop_polling()
    assert not [t for t in threading.enumerate() if t.name == "registry-refresh"], "leaked"
    registry.reset_registry()


def test_reload_waits_two_seconds(state: Any) -> None:
    first = registry.get_registry()
    state.revision = 2
    state.now += 1.99
    assert registry.get_registry() is first
    state.now += 0.01
    assert registry.get_registry() is first  # stale-while-revalidate: nobody waits
    registry.wait_for_refresh()
    second = registry.get_registry()
    assert second is not first
    assert second.tenants[0].version == 2
    assert state.loads == 2
    state.now += 2
    assert registry.get_registry() is second
    assert state.loads == 2


def test_revision_failure_keeps_snapshot(state: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    first = registry.get_registry()
    state.now += 2

    def fail() -> int:
        raise OperationalError("private database details")

    monkeypatch.setattr(registry, "_read_revision", fail)
    assert registry.get_registry() is first
    assert state.loads == 1


def test_first_load_failure_propagates(state: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(alias: str = "default") -> Any:
        raise OperationalError("down")

    monkeypatch.setattr(registry, "_read_config", reader_of(fail))
    with pytest.raises(OperationalError):
        registry.get_registry()
    assert registry.loaded_registry() is None


def test_nested_scopes_pin_until_exit(state: Any) -> None:
    first = registry.get_registry()
    with registry.registry_scope():
        assert registry.get_registry() is first
        state.revision = 2
        state.now += 2
        with registry.registry_scope():
            assert registry.get_registry() is first
        assert registry.loaded_registry() is first
    registry.get_registry()
    registry.wait_for_refresh()
    assert registry.get_registry() is not first


def test_work_and_request_wrappers_pin_registry(state: Any) -> None:
    @contextual
    def work() -> None:
        first = registry.get_registry()
        state.revision += 1
        state.now += 2
        assert registry.get_registry() is first

    work()

    def respond(request: HttpRequest) -> HttpResponse:
        work()
        return HttpResponse()

    assert RegistryScopeMiddleware(respond)(HttpRequest()).status_code == 200
    # A refresh started inside the wrapped calls may have read the revision before its
    # bump; a revision change during a refresh is only seen by the next check. Let it
    # finish so the check below is the one that reads the latest revision.
    registry.wait_for_refresh()
    state.now += 2
    registry.get_registry()
    registry.wait_for_refresh()
    assert registry.get_registry().tenants[0].version == state.revision


def test_concurrent_reload_loads_once_and_nobody_waits(
    state: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = registry.get_registry()
    state.now += 2
    state.revision = 2
    original = registry._read_config
    entered, release = threading.Event(), threading.Event()

    def sources(known: Any) -> Any:
        entered.set()
        assert release.wait(3)
        return original(known)

    monkeypatch.setattr(registry, "_read_config", sources)
    with ThreadPoolExecutor(max_workers=4) as executor:
        try:
            futures = [executor.submit(registry.get_registry) for _ in range(4)]
            assert entered.wait(3)
            # The rebuild is still blocked, yet every caller already has the old snapshot.
            assert [future.result(timeout=3) for future in futures] == [first] * 4
        finally:
            release.set()
    registry.wait_for_refresh()
    assert registry.get_registry().tenants[0].version == 2
    assert state.loads == 2


class FakeConnections:
    """Counts the closes the refresher thread asks for; no database involved."""

    def __init__(self) -> None:
        self.closed = 0

    def __getitem__(self, alias: str) -> Any:
        return SimpleNamespace(
            close_if_unusable_or_obsolete=lambda: None, close_if_health_check_failed=lambda: None
        )

    def close_all(self) -> None:
        self.closed += 1


def test_one_persistent_refresher_keeps_its_connection_unless_a_check_fails(
    state: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeConnections()
    monkeypatch.setattr(registry, "connections", fake)
    registry.get_registry()
    state.revision = 2
    state.now += 2
    registry.get_registry()
    registry.wait_for_refresh()
    first_thread = registry._refresher
    assert first_thread is not None and first_thread.is_alive()
    state.revision = 3
    state.now += 2
    registry.get_registry()
    registry.wait_for_refresh()
    assert registry.get_registry().tenants[0].version == 3
    assert registry._refresher is first_thread  # not a new thread per window
    assert [t.name for t in threading.enumerate()].count("registry-refresh") == 1
    assert fake.closed == 0  # nothing reconnected

    def broken(alias: str = "default") -> Any:
        raise OperationalError("down")

    monkeypatch.setattr(registry, "_read_config", reader_of(broken))
    state.revision = 4
    state.now += 2
    registry.get_registry()
    registry.wait_for_refresh()
    assert fake.closed == 1  # closed because the check failed
    assert registry.get_registry().tenants[0].version == 3  # previous snapshot kept
    assert registry._refresher is first_thread and first_thread.is_alive()


def test_a_forked_process_starts_its_own_refresher(state: Any) -> None:
    registry.get_registry()
    state.revision = 2
    state.now += 2
    registry.get_registry()
    registry.wait_for_refresh()
    parent = registry._refresher
    parent_cv = registry._refresh_cv
    assert parent is not None
    registry._after_fork_in_child()  # what os.register_at_fork runs in the child
    assert registry._refresher is None
    state.revision = 3
    state.now += 2
    registry.get_registry()
    registry.wait_for_refresh()
    assert registry._refresher is not None and registry._refresher is not parent
    assert registry.get_registry().tenants[0].version == 3
    assert registry._poll_interval is None  # a child does not inherit running polling
    # In a real fork the parent's thread does not exist; here it does, so stop it.
    registry.stop_polling()
    registry._stop_target = parent
    with parent_cv:
        parent_cv.notify_all()
    parent.join(5)
    registry._stop_target = None


def test_force_rebuilds_synchronously(state: Any) -> None:
    first = registry.get_registry()
    state.revision = 2
    second = registry.get_registry(force=True)
    assert second is not first
    assert second.tenants[0].version == 2


def test_force_waits_for_the_rebuild_in_flight(state: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    registry.get_registry()
    state.now += 2
    state.revision = 2
    original = registry._read_config
    entered, release = threading.Event(), threading.Event()

    def sources(known: Any) -> Any:
        entered.set()
        assert release.wait(3)
        return original(known)

    monkeypatch.setattr(registry, "_read_config", sources)
    registry.get_registry()
    assert entered.wait(3)
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(registry.get_registry, force=True)
        release.set()
        fresh = future.result(timeout=3)
    assert fresh.tenants[0].version == 2
    assert state.loads == 2  # the forced call reused the finished rebuild


def test_failed_background_rebuild_keeps_snapshot(
    state: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = registry.get_registry()
    state.now += 2
    state.revision = 2

    def broken(alias: str = "default") -> Any:
        raise ValueError("invalid configuration")

    monkeypatch.setattr(registry, "_read_config", reader_of(broken))
    assert registry.get_registry() is first
    registry.wait_for_refresh()
    assert registry.get_registry() is first
    state.now += 2
    monkeypatch.setattr(registry, "_read_config", reader_of(state_sources(state)))
    registry.get_registry()
    registry.wait_for_refresh()
    assert registry.get_registry().tenants[0].version == 2


def state_sources(state: Any) -> Any:
    def sources(alias: str = "default") -> tuple[int, list[registry.TenantSource]]:
        state.loads += 1
        return state.revision, [
            registry.TenantSource("a", tenant_document("a"), version=state.revision)
        ]

    return sources


def test_warm_up_loads_and_never_raises(state: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    registry.warm_up()
    assert registry.loaded_registry() is not None
    registry.reset_registry()

    def fail(alias: str = "default") -> Any:
        raise OperationalError("down")

    monkeypatch.setattr(registry, "_read_config", reader_of(fail))
    registry.warm_up()
    assert registry.loaded_registry() is None


def test_redaction_never_loads_registry(state: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("redaction must not load or query")

    monkeypatch.setattr(registry, "get_registry", fail)
    monkeypatch.setattr(registry, "_read_config", reader_of(fail))
    assert redact("safe message") == "safe message"


def test_a_broken_kept_connection_does_not_skip_the_reload(
    state: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The refresher keeps its connection between rounds; if checking it fails (the
    database restarted, the socket died), it is dropped and the reload still runs."""
    from django.db import connections

    first = registry.get_registry()

    def broken(self: object) -> None:
        raise OperationalError("server closed the connection unexpectedly")

    # On the class: Django connections are per thread, and the refresher has its own.
    monkeypatch.setattr(type(connections["default"]), "close_if_unusable_or_obsolete", broken)
    state.revision = 2
    state.now += 2
    registry.get_registry()
    registry.wait_for_refresh()
    second = registry.get_registry()
    assert second is not first
    assert second.tenants[0].version == 2


# ── polling (refresh-ahead) ───────────────────────────────────────────────


def wait_until(condition: Any, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.01)
    return False


def test_polling_follows_a_change_with_no_caller(state: Any) -> None:
    first = registry.get_registry()
    registry.start_polling(0.02)
    registry.start_polling(0.02)  # idempotent
    state.revision = 2
    # Nobody calls get_registry: the refresher notices by itself.
    assert wait_until(lambda: (loaded := registry.loaded_registry()) is not first and loaded)
    loaded = registry.loaded_registry()
    assert loaded is not None and loaded.tenants[0].version == 2
    assert state.loads == 2
    threads = [t for t in threading.enumerate() if t.name == "registry-refresh"]
    assert len(threads) == 1


def test_stop_polling_stops_and_joins_the_thread(state: Any) -> None:
    registry.get_registry()
    registry.start_polling(0.02)
    assert any(t.name == "registry-refresh" for t in threading.enumerate())
    registry.stop_polling()
    assert not any(t.name == "registry-refresh" for t in threading.enumerate())
    loaded = registry.loaded_registry()
    state.revision = 5
    time.sleep(0.1)
    assert registry.loaded_registry() is loaded  # nobody polls any more
    # A later lazy request still works (a new thread).
    state.now += 2
    registry.get_registry()
    registry.wait_for_refresh()
    registry.stop_polling()


def test_polling_keeps_its_connection_and_drops_it_after_a_failed_check(
    state: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry.get_registry()
    checks, drops = [], []

    def counting() -> int:
        checks.append(1)
        return int(state.revision)

    monkeypatch.setattr(registry, "_read_revision", counting)
    monkeypatch.setattr(registry, "_drop_connection", lambda: drops.append(1))
    registry.start_polling(0.01)
    assert wait_until(lambda: len(checks) >= 5)
    assert drops == []  # healthy checks never reconnect

    def fail() -> int:
        raise OperationalError("private database details")

    monkeypatch.setattr(registry, "_read_revision", fail)
    assert wait_until(lambda: len(drops) >= 1)
    registry.stop_polling()


# ── lookups that do not trust a stale snapshot ────────────────────────────


@pytest.fixture
def grows(state: Any, monkeypatch: pytest.MonkeyPatch) -> Any:
    """Revision 2 adds tenant `b`; counts the revision checks, by whoever makes them."""
    state.checks = 0
    state.by_thread = []

    def counting() -> int:
        state.checks += 1
        state.by_thread.append(threading.current_thread().name)
        return int(state.revision)

    def sources(alias: str = "default") -> tuple[int, list[registry.TenantSource]]:
        state.loads += 1
        slugs = ["a"] + (["b"] if state.revision >= 2 else [])
        return state.revision, [
            registry.TenantSource(s, tenant_document(s), version=state.revision) for s in slugs
        ]

    monkeypatch.setattr(registry, "_read_revision", counting)
    monkeypatch.setattr(registry, "_read_config", reader_of(sources))
    monkeypatch.setattr(registry, "_in_transaction", lambda: False)
    return state


def test_a_miss_checks_the_revision_and_waits_for_the_refresher(grows: Any) -> None:
    registry.get_registry()
    grows.revision = 2  # written by another process; this snapshot is still fresh
    found = registry.tenant_by_slug("b")
    assert found is not None and found.slug == "b"
    assert grows.loads == 2
    assert registry.tenant_by_id(found.id) is found
    assert registry.tenant_by_public_id("whatsapp", found.document.channel.public_id) is found  # type: ignore[union-attr]
    # The caller read the revision once; the rebuild ran on the refresher thread.
    assert grows.by_thread.count("MainThread") == 1
    assert grows.by_thread.count("registry-refresh") == 1


def test_misses_are_throttled_to_one_check_per_window_and_bucket(grows: Any) -> None:
    registry.get_registry()
    assert registry.tenant_by_slug("nope") is None
    assert grows.checks == 1
    assert registry.tenant_by_slug("nope-2") is None  # inside the window: no query
    assert registry.tenant_by_id(uuid.uuid4()) is None
    assert grows.checks == 1
    assert registry.tenant_by_public_id("whatsapp", "zzz") is None  # the public bucket: its own
    assert grows.checks == 2
    assert registry.tenant_by_public_id("whatsapp", "yyy") is None
    assert grows.checks == 2
    grows.now += 1.0
    assert registry.tenant_by_slug("nope") is None  # after the window: one more
    assert grows.checks == 3


def test_the_hit_path_never_queries(grows: Any) -> None:
    registry.get_registry()
    assert registry.tenant_by_slug("a") is not None
    assert grows.checks == 0


def test_a_lookup_inside_a_scope_returns_the_tenant_but_keeps_the_pinned_snapshot(
    grows: Any,
) -> None:
    first = registry.get_registry()
    grows.revision = 2
    with registry.registry_scope():
        assert registry.get_registry() is first
        found = registry.tenant_by_slug("b")
        assert found is not None
        # The unit of work keeps the snapshot it started with: `b` is not in it, and
        # nothing it already saw changed (same objects).
        assert registry.get_registry() is first
        assert registry.loaded_registry() is first
        assert "b" not in first.by_slug and first.by_slug.keys() == {"a"}
    after = registry.get_registry()
    assert after is not first and after.by_slug.keys() == {"a", "b"}


def slow_rebuild(monkeypatch: pytest.MonkeyPatch) -> tuple[threading.Event, threading.Event]:
    """The next rebuild blocks inside the read until `release` is set."""
    entered, release = threading.Event(), threading.Event()
    original = registry._read_config

    def read(known: Any) -> Any:
        entered.set()
        assert release.wait(10)
        return original(known)

    monkeypatch.setattr(registry, "_read_config", read)
    return entered, release


def test_a_miss_during_a_slow_rebuild_returns_within_the_bound_and_never_takes_the_lock(
    grows: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(registry, "MISS_WAIT_SECONDS", 0.3)
    registry.get_registry()
    grows.revision = 2
    grows.now += 2
    entered, release = slow_rebuild(monkeypatch)
    registry.get_registry()  # wakes the refresher: it is now inside the rebuild
    assert entered.wait(3)
    assert registry._registry_lock.locked()  # the rebuild holds it
    started = time.monotonic()
    assert registry.tenant_by_slug("b") is None  # not published yet
    assert time.monotonic() - started < 2  # bounded by MISS_WAIT_SECONDS, not by the rebuild
    assert registry._registry_lock.locked()  # still held by the rebuild: this call never waited
    release.set()
    registry.wait_for_refresh()
    grows.now += 1.0
    assert registry.tenant_by_slug("b") is not None


def test_spray_on_the_public_bucket_does_not_starve_an_internal_lookup(
    grows: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry.get_registry()
    gate, leaving = threading.Event(), threading.Event()
    original = registry._wait_for_newer_config

    def wait() -> None:
        if threading.current_thread().name == "spray":
            gate.set()
            assert leaving.wait(10)
            return
        original()

    monkeypatch.setattr(registry, "_wait_for_newer_config", wait)
    sprayer = threading.Thread(
        target=lambda: registry.tenant_by_public_id("whatsapp", "x"), name="spray"
    )
    sprayer.start()
    try:
        assert gate.wait(3)  # the public bucket's check is in flight
        started = time.monotonic()
        assert registry.tenant_by_slug("a") is not None
        assert registry.tenant_by_slug("nope") is None  # the internal bucket had its slot
        assert time.monotonic() - started < 1
        assert grows.checks == 1  # and it really checked
    finally:
        leaving.set()
        sprayer.join(5)


def test_concurrent_misses_inside_the_window_wait_for_the_check_in_flight(
    grows: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry.get_registry()
    grows.revision = 2
    entered, release = slow_rebuild(monkeypatch)
    results: list[Any] = []
    with ThreadPoolExecutor(max_workers=3) as executor:
        try:
            first = executor.submit(registry.tenant_by_slug, "b")  # the leader
            assert entered.wait(3)  # its check woke the refresher: a rebuild is under way
            others = [executor.submit(registry.tenant_by_slug, "b") for _ in range(2)]
            time.sleep(0.1)
            assert not any(f.done() for f in others)  # waiting, not answering None
        finally:
            release.set()
        results = [f.result(timeout=5) for f in [first, *others]]
    assert all(r is not None and r.slug == "b" for r in results)
    assert grows.loads == 2  # one rebuild for all of them


def test_inside_a_transaction_nothing_is_waited_for_or_forced(
    grows: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry.get_registry()
    grows.revision = 2
    monkeypatch.setattr(registry, "_in_transaction", lambda: True)
    started = time.monotonic()
    assert registry.tenant_by_slug("b") is None
    assert time.monotonic() - started < 0.5
    assert grows.by_thread.count("MainThread") == 0  # not even the revision read
    registry.wait_for_refresh()  # the refresher was asked, and followed
    monkeypatch.setattr(registry, "_in_transaction", lambda: True)
    found = registry.tenant_by_slug("b")  # now in the newest snapshot, answered from it
    assert found is not None


def test_a_database_that_is_down_makes_a_miss_answer_none_without_hanging(
    grows: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry.get_registry()

    def down() -> int:
        raise OperationalError("private database details")

    monkeypatch.setattr(registry, "_read_revision", down)
    started = time.monotonic()
    assert registry.tenant_by_slug("b") is None
    assert time.monotonic() - started < 1


def test_a_request_made_while_a_check_runs_is_not_dropped(
    grows: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The check in flight may have read the revision before the write: one more follows."""
    registry.get_registry()
    grows.now += 2
    grows.revision = 2
    entered, release = slow_rebuild(monkeypatch)
    registry.get_registry()
    assert entered.wait(3)
    before = grows.checks
    registry._request_refresh()  # arrives while it runs
    assert registry._rerun
    release.set()
    registry.wait_for_refresh()
    assert grows.checks > before  # a second check ran after the first one
    assert registry._refresh_state == "idle"


# ── stopping the refresher while someone asks for a check ─────────────────


def test_a_request_during_stop_polling_is_not_left_queued_forever(
    state: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reproduced: the exiting thread answered `idle`, a request set `queued`, and the
    thread was gone: nothing ever ran it and `wait_for_refresh` timed out."""
    registry.get_registry()
    registry.start_polling(0.01)
    leaving, finish = threading.Event(), threading.Event()
    original = registry._drop_connection

    def drop() -> None:
        if threading.current_thread() is not threading.main_thread() and registry._stop_target:
            leaving.set()
            assert finish.wait(10)
        original()

    monkeypatch.setattr(registry, "_drop_connection", drop)
    stopper = threading.Thread(target=registry.stop_polling)
    stopper.start()
    try:
        assert leaving.wait(5)  # the old thread is leaving, still alive
        state.revision = 2
        registry._request_refresh()
    finally:
        finish.set()
        stopper.join(10)
    registry.wait_for_refresh(5)
    assert registry._refresh_state == "idle"
    assert registry.loaded_registry().tenants[0].version == 2  # type: ignore[union-attr]
    assert registry._stop_target is None
