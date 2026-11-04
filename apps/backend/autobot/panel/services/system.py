"""System screen: host readings, retained samples and operational health."""

import socket
import ssl
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

import httpx
from django.conf import settings
from django.core.cache import cache
from django.db import DatabaseError, connections
from django.db.models import Count, Min
from django.utils import timezone
from ninja import Schema
from procrastinate.contrib.django.models import (
    ProcrastinateEvent,
    ProcrastinateJob,
    ProcrastinateWorker,
)

from autobot.ops import system as host
from autobot.ops.models import SystemSample


class SystemOut(Schema):
    machine: dict[str, float | None]
    samples: list[dict[str, Any]]
    services: dict[str, bool]
    database: dict[str, Any]
    queues: list[dict[str, Any]]
    backup: dict[str, Any]
    deploys: list[dict[str, Any]]
    release: str
    tls: dict[str, int | None]


def tls_days_left() -> int | None:
    try:
        hostname = urlsplit(settings.PUBLIC_URL).hostname
        if not hostname:
            return None
        key = f"panel:tls:{hostname}"
        stored = cache.get(key)
        if isinstance(stored, dict):
            value = stored.get("days")
            return value if isinstance(value, int) else None
        days = None
        try:
            context = ssl.create_default_context()
            with (
                socket.create_connection((hostname, 443), timeout=5) as raw,
                context.wrap_socket(raw, server_hostname=hostname) as secure,
            ):
                cert = secure.getpeercert()
                expires = cert.get("notAfter") if cert else None
                if isinstance(expires, str):
                    expiry = datetime.fromtimestamp(ssl.cert_time_to_seconds(expires), UTC)
                    days = (expiry - timezone.now()).days
        except OSError, ValueError, TypeError:
            days = None
        cache.set(key, {"days": days}, timeout=3600)
        return days
    except ValueError:
        return None


def database_info() -> dict[str, Any]:
    try:
        with connections["owner"].cursor() as db:
            db.execute("SELECT 1")
            db.fetchone()
            db.execute("SELECT pg_database_size(current_database())")
            size = db.fetchone()[0]
            db.execute(
                "SELECT schemaname, relname, pg_total_relation_size(relid) AS bytes "
                "FROM pg_stat_user_tables ORDER BY bytes DESC, relname LIMIT 5"
            )
            tables = [
                dict(schema=schema, name=name, bytes=bytes) for schema, name, bytes in db.fetchall()
            ]
        return dict(ok=True, bytes=size, tables=tables)
    except DatabaseError:
        return dict(ok=False, bytes=None, tables=[])


def queue_rows(now: datetime) -> list[dict[str, Any]]:
    rows = list(
        ProcrastinateJob.objects.using("owner")
        .filter(status="todo")
        .values("queue_name")
        .annotate(pending=Count("id"))
    )
    # Same semantics as the retired OperationsSite.state, batched across queues.
    oldest = dict(
        ProcrastinateEvent.objects.using("owner")
        .filter(job__status="todo", type="deferred")
        .values("job__queue_name")
        .annotate(at=Min("at"))
        .values_list("job__queue_name", "at")
    )
    for row in rows:
        at = oldest.get(row["queue_name"])
        row["oldest"] = at
        row["age_s"] = (now - at).total_seconds() if at else None
    return sorted(rows, key=lambda row: row["queue_name"])


def build_system() -> SystemOut:
    now = timezone.now()
    start = now.astimezone(ZoneInfo("Europe/Madrid")).replace(
        day=1, hour=0, minute=0, second=0, microsecond=0
    )
    samples = list(
        SystemSample.objects.using("owner")
        .filter(taken_at__gte=start, taken_at__lte=now)
        .order_by("taken_at", "id")
        .values("taken_at", "cpu_pct", "mem_used_pct", "load1", "disk_used_pct", "db_bytes")
    )
    database = database_info()
    worker = (
        ProcrastinateWorker.objects.using("owner")
        .filter(last_heartbeat__gt=now - timedelta(seconds=60))
        .exists()
    )
    logs_ok = False
    if settings.VICTORIALOGS_URL:
        try:
            response = httpx.get(settings.VICTORIALOGS_URL.rstrip("/") + "/health", timeout=5)
            logs_ok = response.is_success
        except httpx.HTTPError:
            pass
    backup = host.read_backup_status(settings.OPS_STATE_DIR) or {}
    try:
        finished_at = datetime.fromisoformat(backup["finished_at"])
        stale = finished_at.utcoffset() is None or now - finished_at > timedelta(hours=8)
    except KeyError, ValueError, TypeError:
        stale = True
    return SystemOut(
        machine=dict(
            cpu_pct=host.cpu_percent(root=host.PROC),
            mem_used_pct=host.memory(root=host.PROC),
            load1=host.load(root=host.PROC),
            uptime_s=host.uptime_s(root=host.PROC),
            disk_used_pct=host.disk(),
        ),
        samples=[dict(row) for row in samples],
        services=dict(web=True, worker=worker, db=database["ok"], victorialogs=logs_ok),
        database=database,
        queues=queue_rows(now),
        backup={**backup, "stale": stale},
        deploys=[
            row
            for row in reversed(host.read_deploys(settings.OPS_STATE_DIR))
            if isinstance(row, dict)
        ],
        release=settings.RELEASE_SHA,
        tls={"days_left": tls_days_left()},
    )
