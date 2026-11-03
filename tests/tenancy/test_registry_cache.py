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
from tests.tenancy.helpers import PACKS, tenant_yaml


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
            registry.TenantSource("a", tenant_yaml("a"), version=state.revision)
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
    assert registry.get_registry().tenants[0].version == state.revision


def test_concurrent_reload_loads_once(state: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    registry.get_registry()
    state.now += 2
    state.revision = 2
    original = registry.sources_from_database
    entered, release = threading.Event(), threading.Event()
    barrier = threading.Barrier(2)

    def sources(alias: str = "default") -> tuple[int, list[registry.TenantSource]]:
        entered.set()
        assert release.wait(3)
        return original(alias)

    def read() -> registry.Registry:
        barrier.wait(timeout=3)
        return registry.get_registry()

    monkeypatch.setattr(registry, "sources_from_database", sources)
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(read) for _ in range(2)]
        try:
            assert entered.wait(3)
        finally:
            release.set()
        results = [future.result(timeout=3) for future in futures]
    assert results[0] is results[1]
    assert results[0].tenants[0].version == 2
    assert state.loads == 2


def test_redaction_never_loads_registry(state: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("redaction must not load or query")

    monkeypatch.setattr(registry, "get_registry", fail)
    monkeypatch.setattr(registry, "sources_from_database", fail)
    assert redact("safe message") == "safe message"
