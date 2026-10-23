"""The `PackContext` the runtime gives a pack (design.md §8.2): everything external reaches
the pack through it.

- `ctx.lock(key)`: a PostgreSQL session advisory lock (§9.5), taken outside any
  transaction and prefixed with the tenant and the bound calendar.
- `ctx.idem`: idempotency keys bound to the event being processed (`None` in periodic
  handlers, which only use `stable`).
- `ctx.calendar`: only for packs that `needs_calendar`, bound by the runtime to the
  channel's calendar: `calendar_id` on `main`, `test_calendar_id` on `test` (§6.5). The
  pack never picks a calendar nor knows whether the conversation is a test.
"""

import hashlib
import logging
import time
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager, suppress
from typing import Any
from uuid import UUID

from django.conf import settings
from django.db import Error as DatabaseError
from django.db import connections

from core.clock import SystemClock
from core.errors import TransientError
from core.idem import IdemKeys
from core.pack import ContactInfo, PackContext
from flowpilot.runtime.models import Channel
from flowpilot.tenancy.registry import LoadedTenant
from integrations.google_calendar import CalendarClient

log = logging.getLogger(__name__)

LOCK_TIMEOUT_S = 10.0
LOCK_POLL_S = 0.1

type CalendarFactory = Callable[[str], Any]


class CalendarUnavailable(RuntimeError):
    """The pack needs a calendar and this channel has none it may use."""


def google_calendar(calendar_id: str, *, timezone: str = "Europe/Madrid") -> CalendarClient:
    return CalendarClient(
        calendar_id, credentials_file=settings.GOOGLE_SERVICE_ACCOUNT_FILE, timezone=timezone
    )


def build_context(
    tenant: LoadedTenant,
    channel: Channel,
    *,
    contact: ContactInfo | None,
    state: Mapping[str, Any],
    event_id: UUID | None,
    calendars: CalendarFactory = google_calendar,
) -> PackContext:
    """A context for one pack call: a message (`event_id` set) or a periodic handler
    (`contact=None`, `state={}`, `event_id=None`)."""
    if tenant.pack is None or tenant.config is None:
        raise RuntimeError(f"tenant {tenant.slug} is degraded: it has no pack to run")
    calendar_id = bound_calendar_id(tenant, channel)
    info = tenant.info
    extra = {"tenant": info.slug, "channel": str(channel), "event_id": str(event_id or "")}
    return PackContext(
        tenant=info,
        config=tenant.config,
        data=tenant.data,
        contact=contact,
        state=state,
        clock=SystemClock(info.timezone),
        calendar=(
            google_calendar(calendar_id, timezone=str(info.timezone))
            if calendar_id is not None and calendars is google_calendar
            else calendars(calendar_id)
            if calendar_id is not None
            else None
        ),
        lock=lambda key: advisory_lock(f"{info.id}:{calendar_id or '-'}:{key}"),
        idem=IdemKeys(event_id),
        log=logging.LoggerAdapter(logging.getLogger(f"packs.{tenant.pack.name}"), extra),
    )


def bound_calendar_id(tenant: LoadedTenant, channel: Channel) -> str | None:
    """The calendar a pack may use on this channel, or None if it needs none. On the
    `test` channel it is only ever the test calendar (§6.5)."""
    if tenant.pack is None or not tenant.pack.needs_calendar:
        return None
    main = getattr(tenant.config, "calendar_id", None)
    if channel == Channel.MAIN:
        if not main:
            raise CalendarUnavailable(f"tenant {tenant.slug} has no calendar_id")
        return str(main)
    test = getattr(tenant.config, "test_calendar_id", None)
    if not test or _same_calendar(str(test), str(main or "")):
        raise CalendarUnavailable(f"tenant {tenant.slug} has no test_calendar_id of its own")
    return str(test)


@contextmanager
def advisory_lock(key: str) -> Iterator[None]:
    """`pg_try_advisory_lock` in a loop for up to LOCK_TIMEOUT_S, on the default
    connection with no transaction open (a session lock outlives commits, and holding a
    transaction during the pack's external calls is forbidden). Not acquired in time →
    `TransientError`, so the job is retried. Always released."""
    connection = connections["default"]
    if connection.in_atomic_block:
        raise RuntimeError("ctx.lock must not be taken inside a transaction")
    lock_id = _lock_id(key)
    deadline = time.monotonic() + LOCK_TIMEOUT_S
    with connection.cursor() as cursor:
        while True:
            cursor.execute("SELECT pg_try_advisory_lock(%s)", [lock_id])
            (acquired,) = cursor.fetchone() or (False,)
            if acquired:
                break
            if time.monotonic() >= deadline:
                raise TransientError("lock not acquired in time")
            time.sleep(LOCK_POLL_S)
    try:
        yield
    finally:
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_advisory_unlock(%s)", [lock_id])
                (released,) = cursor.fetchone() or (False,)
            if not released:  # e.g. the session was lost while the pack ran
                log.warning("Advisory lock was no longer held when releasing it")
        except DatabaseError as e:
            # Closing the session releases its advisory locks.
            log.warning("Advisory unlock failed (%s): closing the connection", type(e).__name__)
            with suppress(DatabaseError):  # never hide the block's own exception
                connection.close()


def _same_calendar(a: str, b: str) -> bool:
    """Calendar ids look like emails: compared without case nor surrounding spaces."""
    return a.strip().lower() == b.strip().lower()


def _lock_id(key: str) -> int:
    """A signed 64-bit id for PostgreSQL. The key may hold a tenant and a calendar id,
    but only its hash reaches the database."""
    return int.from_bytes(hashlib.sha256(key.encode()).digest()[:8], "big", signed=True)
