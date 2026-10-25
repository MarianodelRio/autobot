"""Persistent, non-personal runtime signals shared by web and worker processes."""

import hashlib
from datetime import datetime
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


def record_calendar(tenant_id: UUID, channel: str, status: str) -> None:
    name = key(tenant_id, channel)
    lock = int.from_bytes(hashlib.sha256(name.encode()).digest()[:8], signed=True)
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(%s)", [lock])
        data = read(tenant_id, channel)
        data.setdefault("observed_at", timezone.now().isoformat())
        data["calendar_errors"] = int(data.get("calendar_errors", 0)) + 1 if status != "ok" else 0
        if status == "denied":
            data["calendar_unavailable"] = True
        elif status == "ok":
            data["calendar_unavailable"] = False
        cache.set(name, data, timeout=None)
