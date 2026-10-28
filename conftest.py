"""Test database setup.

fp_app cannot create databases or tables, so Django's usual test setup (create and migrate
through `default`) is replaced: the test database `test_<name>` already exists (created by
deploy/postgres/init-roles.sh with POSTGRES_TEST_DB), both aliases point to it with their
own roles, and the migrations run as fp_owner. Tests therefore query as fp_app, under RLS.
"""

from collections.abc import Iterator

import pytest
from django.conf import settings
from django.core.management import call_command
from django.core.management.commands import flush
from django.db import connections
from pytest_django import DjangoDbBlocker


@pytest.fixture(scope="session")
def django_db_setup(django_db_blocker: DjangoDbBlocker) -> Iterator[None]:
    for alias in ("default", "owner"):
        name = settings.DATABASES[alias]["NAME"]
        test_name = f"test_{name}"
        connections[alias].close()
        connections[alias].settings_dict["NAME"] = test_name
        settings.DATABASES[alias]["NAME"] = test_name
    with django_db_blocker.unblock():
        call_command("migrate", database="owner", verbosity=0, interactive=False)
    yield


@pytest.fixture(scope="session", autouse=True)
def _flush_as_owner() -> Iterator[None]:
    """Transactional tests empty every table with TRUNCATE after each test, once per alias.
    fp_app may not TRUNCATE (it ignores RLS), so the flush always runs as
    fp_owner. Test-only: the roles keep their privileges."""
    original = flush.Command.handle

    def handle(self: flush.Command, *args: object, **options: object) -> None:
        options["database"] = "owner"
        original(self, *args, **options)

    flush.Command.handle = handle  # type: ignore[method-assign]
    yield
    flush.Command.handle = original  # type: ignore[method-assign]


@pytest.fixture(scope="session", autouse=True)
def _render_scenarios_with_both_adapters() -> Iterator[None]:
    """Every conversation scenario renders its messages with the WhatsApp and Telegram
    adapters; core's harness cannot import them itself."""
    from autobot.channels.testing import check_rendering
    from core.testing.harness import RENDER_CHECKS

    RENDER_CHECKS.append(check_rendering)
    yield
    RENDER_CHECKS.remove(check_rendering)


@pytest.fixture(scope="session", autouse=True)
def _block_external_network() -> Iterator[None]:
    """No real provider calls in CI, even when a worker starts platform periodics.

    Keep loopback/Unix sockets for PostgreSQL; MockTransport and other service doubles
    do not reach these functions. pytest.fail escapes application's except Exception,
    so an accidental external call cannot turn into a silently accepted health issue.
    """
    import ipaddress
    import socket
    from typing import Any

    def check_host(host: Any) -> None:
        if host is None or host in ("", "localhost", b"localhost"):
            return
        try:
            if ipaddress.ip_address(host.decode() if isinstance(host, bytes) else host).is_loopback:
                return
        except ValueError:
            pass
        pytest.fail("External network disabled in tests", pytrace=False)

    original_resolve = socket.getaddrinfo
    original_lookup = socket.gethostbyname
    original_lookup_ex = socket.gethostbyname_ex
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex

    def resolve(host: Any, *args: Any, **kwargs: Any) -> Any:
        check_host(host)
        return original_resolve(host, *args, **kwargs)

    def lookup(host: str) -> str:
        check_host(host)
        return original_lookup(host)

    def lookup_ex(host: str) -> tuple[str, list[str], list[str]]:
        check_host(host)
        return original_lookup_ex(host)

    def connect(sock: socket.socket, address: Any) -> None:
        if sock.family in (socket.AF_INET, socket.AF_INET6):
            check_host(address[0])
        original_connect(sock, address)

    def connect_ex(sock: socket.socket, address: Any) -> int:
        if sock.family in (socket.AF_INET, socket.AF_INET6):
            check_host(address[0])
        return original_connect_ex(sock, address)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(socket, "getaddrinfo", resolve)
        patch.setattr(socket, "gethostbyname", lookup)
        patch.setattr(socket, "gethostbyname_ex", lookup_ex)
        patch.setattr(socket.socket, "connect", connect)
        patch.setattr(socket.socket, "connect_ex", connect_ex)
        yield
