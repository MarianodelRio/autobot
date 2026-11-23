"""System screen: host readings, retained samples and operational health."""

import socket
import ssl
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlsplit

import httpx
from django.conf import settings
from django.core.cache import cache
from django.db import DatabaseError, connections
from django.utils import timezone
from ninja import Schema
from procrastinate.contrib.django.models import ProcrastinateWorker

from autobot.channels.demo.doors import door
from autobot.ops import containers, health
from autobot.ops import system as host
from autobot.ops.models import SystemSample
from autobot.ops.queues import INBOUND_DELAY_S, queue_lags
from autobot.panel.services.month import MADRID
from autobot.runtime.cache import auth_flag_key
from autobot.runtime.jobs import INBOUND, INBOUND_EXT
from autobot.runtime.models import Channel, InboundEvent, OutboundMessage
from autobot.runtime.summary import month_to_date
from autobot.tenancy.registry import get_registry

# Compose services that run a `procrastinate worker` (one process each).
WORKER_SERVICES = ("worker-inbound", "worker-calendar", "worker-periodic", "worker-outbound")
EXPECTED_WORKERS = len(WORKER_SERVICES)

INBOUND_QUEUES = (INBOUND, INBOUND_EXT)


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
    """Per queue: pending and running jobs, the age of the oldest ready job (`age_s`)
    and of the oldest running one (`running_age_s`); see `autobot.ops.queues`."""
    with connections["owner"].cursor() as cursor:
        return [lag.as_row(now) for lag in queue_lags(cursor, now)]


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
        row["queue_name"] in INBOUND_QUEUES
        and row["age_s"] is not None
        and row["age_s"] > INBOUND_DELAY_S
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
    if cache.get(auth_flag_key(name)):
        return IntegrationOut(
            key=key,
            label=label,
            state="critical",
            detail="Envío rechazado por autenticación.",
            checked_at=None,
        )
    snapshot = health.read_snapshot(f"bot:{name}")
    if snapshot is None:
        return IntegrationOut(key=key, label=label, state="unknown", detail=None, checked_at=None)
    if snapshot.issues:
        return IntegrationOut(
            key=key,
            label=label,
            state="critical",
            detail=snapshot.issues[0].message,
            checked_at=snapshot.checked_at,
        )
    return IntegrationOut(
        key=key, label=label, state="ok", detail=None, checked_at=snapshot.checked_at
    )


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
    snapshots = health.read_snapshots(tenant.id for tenant in candidates)
    for tenant in candidates:
        snapshot = snapshots[tenant.id]
        if snapshot is None:
            continue
        if latest_checked is None or snapshot.checked_at > latest_checked:
            latest_checked = snapshot.checked_at
        if any(issue.code.endswith("calendar_unavailable") for issue in snapshot.issues):
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
    start, _ = month_to_date(now, MADRID)
    samples = list(
        SystemSample.objects.using("owner")
        .filter(taken_at__gte=start, taken_at__lte=now)
        .order_by("taken_at", "id")
        .values("taken_at", "cpu_pct", "mem_used_pct", "load1", "disk_used_pct", "db_bytes")
    )
    database = database_info()
    # The four workers. procrastinate registers one `procrastinate_workers` row per worker
    # process, with only an id and a heartbeat (no name, no queues), so the rows cannot be
    # attributed to a service: the count is necessary but not sufficient (a container that
    # restarted leaves its old row for up to 60 s, which could stand in for another dead
    # one). The container snapshot, when fresh, names each service: every `worker-*` must
    # also be running.
    container_state = build_containers(now)
    beating = (
        ProcrastinateWorker.objects.using("owner")
        .filter(last_heartbeat__gt=now - timedelta(seconds=60))
        .count()
    )
    worker = beating >= EXPECTED_WORKERS and _worker_containers_running(container_state)
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
        containers=container_state,
    )


def _worker_containers_running(state: ContainersOut) -> bool:
    """False if a fresh container snapshot shows a worker service that is not running;
    without a usable snapshot the heartbeat count alone decides."""
    if not state.available or state.stale:
        return True
    status = {row.service: row.status for row in state.items}
    return all(status.get(service) == "running" for service in WORKER_SERVICES)


def build_containers(now: datetime) -> ContainersOut:
    assessment = containers.assess(
        containers.read_snapshot(settings.OPS_STATE_DIR), now=now, release_sha=settings.RELEASE_SHA
    )
    return ContainersOut(
        available=assessment.available,
        generated_at=assessment.generated_at,
        stale=assessment.stale,
        maintenance=assessment.maintenance,
        items=[ContainerOut.model_validate(row) for row in assessment.services],
    )
