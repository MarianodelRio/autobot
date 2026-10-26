"""`build_context`: the advisory lock competing with
another database session, idempotency keys and the calendar bound to each channel.
Transactional: the lock is a session lock taken outside any transaction."""

import dataclasses
import threading
import time
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import psycopg
import pytest
from django.conf import settings
from django.db import OperationalError, connections, transaction
from pydantic import BaseModel

from core.errors import TransientError
from core.pack import ContactInfo
from flowpilot.runtime import context
from flowpilot.runtime.context import (
    CalendarUnavailable,
    advisory_lock,
    bound_calendar_id,
    build_context,
)
from flowpilot.runtime.models import Channel
from flowpilot.tenancy.registry import LoadedTenant
from flowpilot.tenancy.schema import TelegramChannel, TenantFile
from tests.tenancy.helpers import tenant_yaml
from tests.toy_pack import pack as toy

pytestmark = pytest.mark.django_db(transaction=True, databases=["default", "owner"])

EVENT_ID = uuid.UUID("01920000-0000-7000-8000-0000000000e1")


class CalendarConfig(BaseModel):
    calendar_id: str = "real@group.calendar.google.com"
    test_calendar_id: str | None = "test@group.calendar.google.com"


CALENDAR_PACK = dataclasses.replace(toy.pack, needs_calendar=True, config_schema=CalendarConfig)


def loaded(pack: Any = toy.pack, config: BaseModel | None = None) -> LoadedTenant:
    file = TenantFile.model_validate(tenant_yaml("demo"))
    return LoadedTenant(file=file, path=Path("."), pack=pack, config=config or pack.config_schema())


class Calendars:
    """A fake CalendarPort factory that records which calendars were bound."""

    def __init__(self) -> None:
        self.bound: list[str] = []

    def __call__(self, calendar_id: str) -> str:
        self.bound.append(calendar_id)
        return f"port:{calendar_id}"


@pytest.fixture
def other_session() -> Iterator[psycopg.Connection[Any]]:
    """Another PostgreSQL session (another backend process), as another worker would be."""
    db = settings.DATABASES["default"]
    with psycopg.connect(
        host=db["HOST"],
        port=db["PORT"],
        dbname=db["NAME"],
        user=db["USER"],
        password=db["PASSWORD"],
        autocommit=True,
    ) as conn:
        yield conn


def try_lock(session: psycopg.Connection[Any], lock_id: int) -> bool:
    row = session.execute("SELECT pg_try_advisory_lock(%s)", [lock_id]).fetchone()
    assert row is not None
    return bool(row[0])


# ── Context ───────────────────────────────────────────────────────────────


def test_message_context() -> None:
    tenant = loaded()
    contact = ContactInfo(uuid.uuid7(), "34600000001", "+34600000001", "Lucía", False)
    ctx = build_context(tenant, Channel.MAIN, contact=contact, state={"step": 1}, event_id=EVENT_ID)
    assert ctx.tenant == tenant.info and ctx.contact == contact and ctx.state == {"step": 1}
    assert ctx.config == tenant.config and ctx.calendar is None  # the toy pack needs none
    assert ctx.clock.now().tzinfo == tenant.info.timezone
    assert ctx.idem.event("booking") == f"booking:{EVENT_ID}"
    assert ctx.idem.stable("reminder:x:1") == "reminder:x:1"


def test_periodic_context_has_no_event_key() -> None:
    ctx = build_context(loaded(), Channel.MAIN, contact=None, state={}, event_id=None)
    with pytest.raises(RuntimeError):
        ctx.idem.event("booking")


# ── Calendar per channel ──────────────────────────────────────────────────


def test_main_binds_the_real_calendar_and_test_the_test_calendar() -> None:
    calendars = Calendars()
    tenant = loaded(CALENDAR_PACK)
    main = build_context(
        tenant, Channel.MAIN, contact=None, state={}, event_id=None, calendars=calendars
    )
    test = build_context(
        tenant, Channel.TEST, contact=None, state={}, event_id=None, calendars=calendars
    )
    assert main.calendar == "port:real@group.calendar.google.com"
    assert test.calendar == "port:test@group.calendar.google.com"
    assert calendars.bound == ["real@group.calendar.google.com", "test@group.calendar.google.com"]


@pytest.mark.parametrize(
    "config",
    [
        CalendarConfig(test_calendar_id=None),
        CalendarConfig(test_calendar_id=""),
        CalendarConfig(test_calendar_id="real@group.calendar.google.com"),  # the real one
        CalendarConfig(test_calendar_id=" Real@Group.Calendar.Google.com "),
    ],
)
def test_the_test_channel_never_gets_the_real_calendar(config: CalendarConfig) -> None:
    calendars = Calendars()
    tenant = loaded(CALENDAR_PACK, config)
    with pytest.raises(CalendarUnavailable):
        build_context(
            tenant, Channel.TEST, contact=None, state={}, event_id=None, calendars=calendars
        )
    assert calendars.bound == []  # the factory never saw calendar_id


def test_the_default_factory_builds_a_lazy_google_client() -> None:
    from integrations.google_calendar import CalendarClient

    ctx = build_context(loaded(CALENDAR_PACK), Channel.MAIN, contact=None, state={}, event_id=None)
    assert isinstance(ctx.calendar, CalendarClient)


def test_lock_key_is_prefixed_with_tenant_and_bound_calendar(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    keys: list[str] = []
    monkeypatch.setattr(context, "advisory_lock", lambda key: keys.append(key))
    tenant = loaded(CALENDAR_PACK)
    for channel in (Channel.MAIN, Channel.TEST):
        ctx = build_context(
            tenant, channel, contact=None, state={}, event_id=None, calendars=Calendars()
        )
        ctx.lock("cal:2026-10-09")
    assert keys == [
        f"{tenant.id}:real@group.calendar.google.com:cal:2026-10-09",
        f"{tenant.id}:test@group.calendar.google.com:cal:2026-10-09",
    ]
    assert bound_calendar_id(loaded(), Channel.TEST) is None


# ── Advisory lock ─────────────────────────────────────────────────────────


def test_lock_waits_for_another_session_then_times_out(
    other_session: psycopg.Connection[Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(context, "LOCK_TIMEOUT_S", 0.3)
    lock_id = context._lock_id("t:cal:day")
    other_session.execute("SELECT pg_advisory_lock(%s)", [lock_id])
    started = time.monotonic()
    with pytest.raises(TransientError), advisory_lock("t:cal:day"):
        pass
    assert time.monotonic() - started >= 0.3

    other_session.execute("SELECT pg_advisory_unlock(%s)", [lock_id])
    with advisory_lock("t:cal:day"):
        # Held now: the other session cannot take it.
        assert try_lock(other_session, lock_id) is False
    assert try_lock(other_session, lock_id) is True  # released on exit
    other_session.execute("SELECT pg_advisory_unlock(%s)", [lock_id])


def test_lock_is_released_when_the_block_fails(other_session: psycopg.Connection[Any]) -> None:
    lock_id = context._lock_id("t:cal:fail")
    with pytest.raises(ValueError), advisory_lock("t:cal:fail"):
        raise ValueError("pack error")
    assert try_lock(other_session, lock_id) is True
    other_session.execute("SELECT pg_advisory_unlock(%s)", [lock_id])


def test_two_competing_workers_never_overlap() -> None:
    """Two threads, each with its own database session, booking the same day."""
    inside: list[str] = []
    overlaps: list[str] = []

    def book(name: str) -> None:
        try:
            with advisory_lock("t:cal:race"):
                if inside:
                    overlaps.append(name)
                inside.append(name)
                time.sleep(0.2)
                inside.remove(name)
        finally:
            connections.close_all()

    threads = [threading.Thread(target=book, args=(n,)) for n in ("a", "b")]
    started = time.monotonic()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert overlaps == []
    assert time.monotonic() - started >= 0.4  # the second one really waited


def test_a_failed_unlock_closes_the_session_and_frees_the_lock(
    other_session: psycopg.Connection[Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    lock_id = context._lock_id("t:cal:unlock")
    connection = connections["default"]
    original = connection.cursor
    with advisory_lock("t:cal:unlock"):

        def broken_cursor() -> Any:
            raise OperationalError("server closed the connection")

        monkeypatch.setattr(connection, "cursor", broken_cursor)
    monkeypatch.setattr(connection, "cursor", original)
    assert connection.connection is None  # closed
    assert try_lock(other_session, lock_id) is True
    other_session.execute("SELECT pg_advisory_unlock(%s)", [lock_id])


def test_a_degraded_tenant_has_no_context() -> None:
    tenant = dataclasses.replace(loaded(), pack=None, config=None)
    with pytest.raises(RuntimeError, match="degraded"):
        build_context(tenant, Channel.MAIN, contact=None, state={}, event_id=None)


def test_lock_refuses_an_open_transaction() -> None:
    with transaction.atomic(), pytest.raises(RuntimeError), advisory_lock("t:x"):
        pass


def test_phone_contact_capability_is_only_for_main_whatsapp() -> None:
    main = build_context(
        loaded(CALENDAR_PACK),
        Channel.MAIN,
        contact=None,
        state={},
        event_id=None,
        calendars=Calendars(),
    )
    test = build_context(
        loaded(CALENDAR_PACK),
        Channel.TEST,
        contact=None,
        state={},
        event_id=None,
        calendars=Calendars(),
    )
    assert main.can_contact_by_phone and not test.can_contact_by_phone
    tenant = loaded(CALENDAR_PACK)
    file = tenant.file.model_copy(
        update={
            "channel": TelegramChannel(
                type="telegram", public_id="telegrampublic", bot_username="salon_bot"
            )
        }
    )
    telegram = build_context(
        dataclasses.replace(tenant, file=file),
        Channel.MAIN,
        contact=None,
        state={},
        event_id=None,
        calendars=Calendars(),
    )
    assert not telegram.can_contact_by_phone
