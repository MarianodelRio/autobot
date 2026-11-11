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

from autobot.channels.demo.doors import door
from autobot.ops import containers
from autobot.ops import system as host
from autobot.ops.models import SystemSample
from autobot.runtime.models import Channel, InboundEvent, OutboundMessage
from autobot.tenancy.registry import get_registry

EXPECTED_WORKERS = 2  # worker-inbound and worker-outbound (compose)


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
    flow: FlowOut
    integrations: list[IntegrationOut]
    containers: ContainersOut


class ContainerOut(Schema):
    service: str
    name: str | None
    status: str
    health: str
    restart_count: int
    oom_killed: bool
    started_at: datetime | None
    image_tag: str | None
    image_matches: bool | None
    level: str
    reason: str | None


class ContainersOut(Schema):
    available: bool
    generated_at: datetime | None
    stale: bool
    maintenance: str | None
    items: list[ContainerOut]


class FlowOut(Schema):
    state: str
    reason: str | None
    last_inbound_at: datetime | None
    last_outbound_at: datetime | None
    received_1h: int
    answered_1h: int
    failed_1h: int


class IntegrationOut(Schema):
    key: str
    label: str
    state: str
    detail: str | None
    checked_at: datetime | None


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


def flow(now: datetime, queues: list[dict[str, Any]]) -> FlowOut:
    ids = [tenant.id for tenant in get_registry().by_slug.values()]
    hour_ago = now - timedelta(hours=1)
    inbound = InboundEvent.objects.using("owner").filter(tenant_id__in=ids, kind="message")
    outbound = OutboundMessage.objects.using("owner").filter(tenant_id__in=ids)
    received_1h = inbound.filter(received_at__gte=hour_ago).count()
    answered_1h = outbound.filter(sent_at__gte=hour_ago).count()
    failed_1h = inbound.filter(status="failed", received_at__gte=hour_ago).count() + (
        outbound.filter(status__in=["failed", "unknown"], created_at__gte=hour_ago).count()
    )
    last_inbound_at = inbound.order_by("-received_at").values_list("received_at", flat=True).first()
    last_outbound_at = (
        outbound.exclude(sent_at=None)
        .order_by("-sent_at")
        .values_list("sent_at", flat=True)
        .first()
    )
    delayed = any(
        row["queue_name"] == "inbound" and row["age_s"] is not None and row["age_s"] > 120
        for row in queues
    )
    if delayed or failed_1h:
        state, reason = (
            "critical",
            (
                "Trabajo de entrada pendiente más de 2 minutos."
                if delayed
                else f"{failed_1h} fallos en la última hora."
            ),
        )
    elif received_1h == 0 and answered_1h == 0:
        state, reason = "idle", "Sin tráfico reciente."
    else:
        state, reason = "ok", None
    return FlowOut(
        state=state,
        reason=reason,
        last_inbound_at=last_inbound_at,
        last_outbound_at=last_outbound_at,
        received_1h=received_1h,
        answered_1h=answered_1h,
        failed_1h=failed_1h,
    )


def _bot_integration(key: str, label: str, name: str, off: bool) -> IntegrationOut:
    if off:
        return IntegrationOut(key=key, label=label, state="off", detail=None, checked_at=None)
    if cache.get(f"bot:{name}:auth"):
        return IntegrationOut(
            key=key,
            label=label,
            state="critical",
            detail="Envío rechazado por autenticación.",
            checked_at=None,
        )
    cached = cache.get(f"health:bot:{name}")
    if not isinstance(cached, dict):
        return IntegrationOut(key=key, label=label, state="unknown", detail=None, checked_at=None)
    checked_at = datetime.fromtimestamp(cached["checked_at"], tz=UTC)
    issues = cached.get("issues") or []
    if issues:
        detail = getattr(issues[0], "message", None)
        return IntegrationOut(
            key=key, label=label, state="critical", detail=detail, checked_at=checked_at
        )
    return IntegrationOut(key=key, label=label, state="ok", detail=None, checked_at=checked_at)


def _calendar_integration() -> IntegrationOut:
    candidates = [
        tenant
        for tenant in get_registry().by_slug.values()
        if tenant.document.status != "offboarded"
        and tenant.pack is not None
        and any(p.name == "calendar_sweep" for p in tenant.pack.periodic)
    ]
    if not candidates:
        return IntegrationOut(
            key="calendar", label="Calendar", state="off", detail=None, checked_at=None
        )
    total = len(candidates)
    accessible = 0
    failing = 0
    latest_checked: datetime | None = None
    for tenant in candidates:
        cached = cache.get(f"health:{tenant.id}")
        if not isinstance(cached, dict):
            continue
        checked_at = datetime.fromtimestamp(cached["checked_at"], tz=UTC)
        if latest_checked is None or checked_at > latest_checked:
            latest_checked = checked_at
        issues = cached.get("issues") or []
        if any(getattr(issue, "code", "").endswith("calendar_unavailable") for issue in issues):
            failing += 1
        else:
            accessible += 1
    unchecked = total - accessible - failing
    if accessible + failing == 0:
        return IntegrationOut(
            key="calendar", label="Calendar", state="unknown", detail=None, checked_at=None
        )
    state = "critical" if failing else "unknown" if unchecked else "ok"
    detail = f"{accessible} de {total} accesibles"
    if unchecked:
        detail += f" · {unchecked} sin comprobar"
    return IntegrationOut(
        key="calendar", label="Calendar", state=state, detail=detail, checked_at=latest_checked
    )


def integrations() -> list[IntegrationOut]:
    return [
        _bot_integration(
            "bot:notify", "Bot de avisos", "notify", off=not settings.NOTIFY_BOT_TOKEN
        ),
        _bot_integration(
            "bot:demo_tg", "Demo Telegram", "demo_tg", off=door(Channel.DEMO_TG) is None
        ),
        _bot_integration(
            "bot:demo_wa", "Demo WhatsApp", "demo_wa", off=door(Channel.DEMO_WA) is None
        ),
        _calendar_integration(),
    ]


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
    # worker-inbound and worker-outbound (X14): green only while both beat, so one
    # dead worker is not hidden by the other.
    worker = (
        ProcrastinateWorker.objects.using("owner")
        .filter(last_heartbeat__gt=now - timedelta(seconds=60))
        .count()
        >= EXPECTED_WORKERS
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
    queues = queue_rows(now)
    return SystemOut(
        machine=dict(
            cpu_pct=host.cpu_percent(root=host.PROC),
            mem_used_pct=host.memory(root=host.PROC),
            load1=host.load(root=host.PROC),
            uptime_s=host.uptime_s(root=host.PROC),
            disk_used_pct=host.disk(),
        ),
        samples=[dict(row) for row in samples],
        services=dict(worker=worker, db=database["ok"], victorialogs=logs_ok),
        database=database,
        queues=queues,
        backup={**backup, "stale": stale},
        deploys=[
            row
            for row in reversed(host.read_deploys(settings.OPS_STATE_DIR))
            if isinstance(row, dict)
        ],
        release=settings.RELEASE_SHA,
        tls={"days_left": tls_days_left()},
        flow=flow(now, queues),
        integrations=integrations(),
        containers=build_containers(now),
    )


def build_containers(now: datetime) -> ContainersOut:
    assessment = containers.assess(
        containers.read_snapshot(settings.OPS_STATE_DIR), now=now, release_sha=settings.RELEASE_SHA
    )
    return ContainersOut(
        available=assessment.available,
        generated_at=assessment.generated_at,
        stale=assessment.stale,
        maintenance=assessment.maintenance,
        items=[
            ContainerOut(
                service=row.service,
                name=row.name,
                status=row.status,
                health=row.health,
                restart_count=row.restart_count,
                oom_killed=row.oom_killed,
                started_at=row.started_at,
                image_tag=row.image_tag,
                image_matches=row.image_matches,
                level=row.level,
                reason=row.reason,
            )
            for row in assessment.services
        ],
    )
