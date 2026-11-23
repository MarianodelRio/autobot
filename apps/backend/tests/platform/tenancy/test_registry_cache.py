"""Revision polling and work scopes retain a consistent registry snapshot."""

import threading
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
from tests.platform.tenancy.helpers import PACKS, tenant_document


@pytest.fixture
def state(monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    registry.reset_registry()
    state = SimpleNamespace(now=10.0, revision=1, loads=0)
    monkeypatch.setattr(registry, "time", SimpleNamespace(monotonic=lambda: state.now))
    monkeypatch.setattr("packs.registry.PACKS", PACKS)
    monkeypatch.setattr(registry, "_read_revision", lambda: state.revision)

    def sources(alias: str = "default") -> tuple[int, list[registry.TenantSource]]:
        state.loads += 1
        return state.revision, [
            registry.TenantSource("a", tenant_document("a"), version=state.revision)
        ]

    monkeypatch.setattr(registry, "sources_from_database", sources)
    yield state
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

    monkeypatch.setattr(registry, "sources_from_database", fail)
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
    original = registry.sources_from_database
    entered, release = threading.Event(), threading.Event()

    def sources(alias: str = "default") -> tuple[int, list[registry.TenantSource]]:
        entered.set()
        assert release.wait(3)
        return original(alias)

    monkeypatch.setattr(registry, "sources_from_database", sources)
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

    monkeypatch.setattr(registry, "sources_from_database", broken)
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
    assert parent is not None
    registry._after_fork_in_child()  # what os.register_at_fork runs in the child
    assert registry._refresher is None
    state.revision = 3
    state.now += 2
    registry.get_registry()
    registry.wait_for_refresh()
    assert registry._refresher is not None and registry._refresher is not parent
    assert registry.get_registry().tenants[0].version == 3


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
    original = registry.sources_from_database
    entered, release = threading.Event(), threading.Event()

    def sources(alias: str = "default") -> tuple[int, list[registry.TenantSource]]:
        entered.set()
        assert release.wait(3)
        return original(alias)

    monkeypatch.setattr(registry, "sources_from_database", sources)
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

    monkeypatch.setattr(registry, "sources_from_database", broken)
    assert registry.get_registry() is first
    registry.wait_for_refresh()
    assert registry.get_registry() is first
    state.now += 2
    monkeypatch.setattr(registry, "sources_from_database", state_sources(state))
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

    monkeypatch.setattr(registry, "sources_from_database", fail)
    registry.warm_up()
    assert registry.loaded_registry() is None


def test_redaction_never_loads_registry(state: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("redaction must not load or query")

    monkeypatch.setattr(registry, "get_registry", fail)
    monkeypatch.setattr(registry, "sources_from_database", fail)
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
