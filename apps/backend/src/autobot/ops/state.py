"""Persistent, non-personal runtime signals shared by web and worker processes."""

import hashlib
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from django.core.cache import cache
from django.db import connection, transaction
from django.utils import timezone


def key(tenant_id: UUID, channel: str) -> str:
    return f"runtime:{tenant_id}:{channel}"


def read(tenant_id: UUID, channel: str) -> dict[str, Any]:
    value = cache.get(key(tenant_id, channel))
    return value if isinstance(value, dict) else {}


def record(tenant_id: UUID, channel: str, *, failed: bool, sweep: bool = False) -> None:
    """Serialize read/modify/write; never expires while the tenant exists.

    Values contain counts and timestamps, never exceptions or calendar/customer ids.
    A success resets the consecutive failure counter; only a completed sweep updates
    last_sweep. The observation baseline detects a sweep that never completed.
    """
    name = key(tenant_id, channel)
    lock = int.from_bytes(hashlib.sha256(name.encode()).digest()[:8], signed=True)
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(%s)", [lock])
        data = read(tenant_id, channel)
        data.setdefault("observed_at", timezone.now().isoformat())
        data["errors"] = int(data.get("errors", 0)) + 1 if failed else 0
        if sweep and not failed:
            data["last_sweep"] = timezone.now().isoformat()
        cache.set(name, data, timeout=None)


def sweep_baseline(tenant_id: UUID, channel: str, now: datetime) -> datetime:
    name = key(tenant_id, channel)
    # add establishes a baseline also for a periodic task that never ran.
    cache.add(name, {"observed_at": now.isoformat(), "errors": 0}, timeout=None)
    data = read(tenant_id, channel)
    return datetime.fromisoformat(data.get("last_sweep") or data["observed_at"])


def _calendar_state(data: dict[str, Any], status: str) -> tuple[int, bool]:
    errors = int(data.get("calendar_errors", 0)) + 1 if status != "ok" else 0
    unavailable = bool(data.get("calendar_unavailable", False))
    if status == "denied":
        unavailable = True
    elif status == "ok":
        unavailable = False
    return errors, unavailable


def record_calendar(tenant_id: UUID, channel: str, status: str) -> None:
    """Most calls observe "ok" with nothing new to say: skip the advisory lock and the
    write (one per Calendar call otherwise) unless the state actually changes."""
    name = key(tenant_id, channel)
    data = read(tenant_id, channel)
    if "observed_at" in data and _calendar_state(data, status) == (
        int(data.get("calendar_errors", 0)),
        bool(data.get("calendar_unavailable", False)),
    ):
        return
    lock = int.from_bytes(hashlib.sha256(name.encode()).digest()[:8], signed=True)
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(%s)", [lock])
        data = read(tenant_id, channel)
        data.setdefault("observed_at", timezone.now().isoformat())
        data["calendar_errors"], data["calendar_unavailable"] = _calendar_state(data, status)
        cache.set(name, data, timeout=None)


# ── Provider outages (ADR-024) ─────────────────────────────────────────────
# The outbound breaker of a worker (`autobot.runtime.breaker`) writes here when it opens,
# closes and, while open, after each failed probe. `ops_check` raises one `provider_outage`
# alert from it; a signal nobody refreshed for PROVIDER_STALE_AFTER (a worker that died
# with the breaker open) counts as closed.

PROVIDER_STALE_AFTER = timedelta(minutes=10)


def _provider_key(provider: str) -> str:
    return f"runtime:provider:{provider}"


def record_provider(provider: str, *, is_open: bool) -> None:
    cache.set(
        _provider_key(provider),
        {"open": is_open, "at": timezone.now().isoformat()},
        timeout=None,
    )


def providers_down(now: datetime) -> list[str]:
    """The providers whose breaker is open and whose signal is fresh."""
    down = []
    for provider in ("telegram", "whatsapp"):
        data = cache.get(_provider_key(provider))
        if not isinstance(data, dict) or not data.get("open"):
            continue
        try:
            at = datetime.fromisoformat(str(data["at"]))
        except KeyError, ValueError:
            continue
        if now - at <= PROVIDER_STALE_AFTER:
            down.append(provider)
    return down


def providers_recovering(now: datetime, grace: timedelta) -> list[str]:
    """The providers whose breaker closed less than `grace` ago (the signal is only
    written on a change, so a closed one with a recent time is an outage that just ended).
    The tenants' own cached health results, taken during it, still say "unavailable"."""
    recovering = []
    for provider in ("telegram", "whatsapp"):
        data = cache.get(_provider_key(provider))
        if not isinstance(data, dict) or data.get("open"):
            continue
        try:
            at = datetime.fromisoformat(str(data["at"]))
        except KeyError, ValueError:
            continue
        if now - at <= grace:
            recovering.append(provider)
    return recovering
