"""`GET overview`: the whole Resumen screen in one call (DESIGN §9.4).

Every query here crosses tenants, so it runs `.using("owner")` explicitly (DESIGN
§3.3) — this is panel service code, not a tenant's own request. Figures grouped by
tenant are grouped by `tenant_id` in SQL, never fetched one tenant at a time; the one
exception is the handful of queries repeated per distinct tenant timezone (DESIGN
§6.3: "mes en curso" uses each tenant's own zone for its own figures), bounded by how
many timezones are actually in use, not by how many tenants there are.
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from django.conf import settings
from django.core.cache import cache
from django.db import connections
from django.db.models import Count, Max, Q, Sum
from django.db.models.functions import TruncDate
from django.utils import timezone
from ninja import Schema

from autobot.ops import system
from autobot.ops.models import OpsAlert
from autobot.ops.status import tenant_status
from autobot.runtime import costs
from autobot.runtime.models import InboundEvent, MetricEvent, OutboundMessage
from autobot.runtime.summary import month_to_date
from autobot.tenancy.registry import LoadedTenant, get_registry

MADRID = ZoneInfo("Europe/Madrid")
STALE_MINUTES = 10
MAX_PROBLEMS = 5
MAX_RECENT_ALERTS = 5
METRIC_LABELS: dict[str, str] = {
    "schedule_query": "Consultas de horario",
}


class DayCount(Schema):
    date: date
    inbound: int
    outbound: int


class MetricTotal(Schema):
    pack: str
    kind: str
    label: str
    total: Decimal


class MonthSummary(Schema):
    start: datetime
    inbound: int
    outbound: int
    users: int
    billable: int
    cost_eur: Decimal
    by_day: list[DayCount]
    metrics: list[MetricTotal]


class TenantCounts(Schema):
    active: int
    onboarding: int
    paused: int
    demos: int
    total: int


class ProblemBrief(Schema):
    text: str
    tenant: str | None
    link: str | None


class StatusBlock(Schema):
    level: Literal["ok", "warning", "critical"]
    problems: list[ProblemBrief]


class SystemBrief(Schema):
    cpu_pct: float | None
    mem_used_pct: float | None
    disk_used_pct: float | None
    last_backup_at: datetime | None
    backup_ok: bool | None
    tls_days_left: int | None
    release: str
    deployed_at: datetime | None


class AlertBrief(Schema):
    id: UUID
    kind: str
    tenant: str | None
    severity: str
    text: str
    occurred_at: datetime
    resolved: bool


class TenantRow(Schema):
    slug: str
    name: str
    pack: str
    channel: Literal["whatsapp", "telegram", "demo"]
    status: str
    health: str
    health_reasons: list[str]
    health_checked_at: datetime | None
    inbound_month: int
    outbound_month: int
    cost_eur_month: Decimal
    last_activity_at: datetime | None


class Overview(Schema):
    generated_at: datetime
    status: StatusBlock
    tenants: TenantCounts
    month: MonthSummary
    tenant_rows: list[TenantRow]
    incidents_open: int
    system: SystemBrief
    recent_alerts: list[AlertBrief]


def _active_tenants() -> list[LoadedTenant]:
    return [t for t in get_registry().tenants if t.document.status != "offboarded"]


def _open_alerts() -> list[OpsAlert]:
    return list(OpsAlert.objects.using("owner").filter(resolved_at__isnull=True))


def _channel_label(tenant: LoadedTenant) -> Literal["whatsapp", "telegram", "demo"]:
    if tenant.document.channel is not None:
        return tenant.document.channel.type
    return "demo"


def _health_checked_at(tenant_id: UUID) -> datetime | None:
    health = cache.get(f"health:{tenant_id}")
    if isinstance(health, dict) and "checked_at" in health:
        return datetime.fromtimestamp(health["checked_at"], tz=UTC)
    return None


def _stale_outbound(now: datetime, tenant_ids: list[UUID]) -> int:
    return (
        OutboundMessage.objects.using("owner")
        .filter(
            Q(status="failed")
            | Q(status="unknown", unknown_at__lt=now - timedelta(minutes=STALE_MINUTES)),
            tenant_id__in=tenant_ids,
        )
        .count()
    )


def _failed_jobs() -> int:
    with connections["default"].cursor() as cursor:
        cursor.execute("SELECT count(*) FROM procrastinate_jobs WHERE status = 'failed'")
        (count,) = cursor.fetchone()
        return int(count)


def tenant_rows(now: datetime) -> list[TenantRow]:
    """One `TenantRow` per non-offboarded tenant. Reused by `GET tenants` (T16a)."""
    tenants = _active_tenants()
    open_alerts = _open_alerts()
    by_tz: dict[ZoneInfo, list[LoadedTenant]] = defaultdict(list)
    for tenant in tenants:
        by_tz[tenant.info.timezone].append(tenant)

    inbound_month: dict[UUID, int] = {}
    outbound_month: dict[UUID, int] = {}
    pricing_counts: dict[UUID, dict[str | None, int]] = defaultdict(dict)
    for tz, group in by_tz.items():
        start, _ = month_to_date(now, tz)
        ids = [t.id for t in group]
        inbound_month.update(
            InboundEvent.objects.using("owner")
            .filter(tenant_id__in=ids, kind="message", received_at__gte=start)
            .values("tenant_id")
            .annotate(total=Count("id"))
            .values_list("tenant_id", "total")
        )
        outbound_month.update(
            OutboundMessage.objects.using("owner")
            .filter(tenant_id__in=ids, status="sent", sent_at__gte=start)
            .values("tenant_id")
            .annotate(total=Count("id"))
            .values_list("tenant_id", "total")
        )
        for row in (
            OutboundMessage.objects.using("owner")
            .filter(tenant_id__in=ids, billable=True, sent_at__gte=start)
            .values("tenant_id", "pricing_category")
            .annotate(total=Count("id"))
        ):
            pricing_counts[row["tenant_id"]][row["pricing_category"]] = row["total"]

    all_ids = [t.id for t in tenants]
    last_received: dict[UUID, datetime] = dict(
        InboundEvent.objects.using("owner")
        .filter(tenant_id__in=all_ids)
        .values("tenant_id")
        .annotate(latest=Max("received_at"))
        .values_list("tenant_id", "latest")
    )
    last_sent: dict[UUID, datetime] = dict(
        OutboundMessage.objects.using("owner")
        .filter(tenant_id__in=all_ids, status="sent")
        .values("tenant_id")
        .annotate(latest=Max("sent_at"))
        .values_list("tenant_id", "latest")
    )

    rows = []
    for tenant in tenants:
        health = tenant_status(tenant, open_alerts=open_alerts)
        received = last_received.get(tenant.id)
        sent = last_sent.get(tenant.id)
        last_activity = max((d for d in (received, sent) if d is not None), default=None)
        rows.append(
            TenantRow(
                slug=tenant.slug,
                name=tenant.document.name,
                pack=tenant.document.pack,
                channel=_channel_label(tenant),
                status=tenant.document.status,
                health=health.level,
                health_reasons=health.reasons,
                health_checked_at=_health_checked_at(tenant.id),
                inbound_month=inbound_month.get(tenant.id, 0),
                outbound_month=outbound_month.get(tenant.id, 0),
                cost_eur_month=costs.cost_of(pricing_counts.get(tenant.id, {})),
                last_activity_at=last_activity,
            )
        )
    return rows


def _tenant_counts(tenants: list[LoadedTenant]) -> TenantCounts:
    active = onboarding = paused = demos = 0
    for tenant in tenants:
        if tenant.is_demo:
            demos += 1
        elif tenant.document.status == "active":
            active += 1
        elif tenant.document.status == "onboarding":
            onboarding += 1
        elif tenant.document.status == "paused":
            paused += 1
    return TenantCounts(
        active=active, onboarding=onboarding, paused=paused, demos=demos, total=len(tenants)
    )


@dataclass(frozen=True)
class _GlobalMonth:
    inbound: int
    outbound: int
    users: int
    billable: int
    cost_eur: Decimal
    by_day: list[DayCount]
    metrics: list[MetricTotal]


def _global_month(now: datetime, tenants: list[LoadedTenant]) -> tuple[datetime, _GlobalMonth]:
    start, _ = month_to_date(now, MADRID)
    ids = [t.id for t in tenants]
    pack_by_id = {t.id: t.document.pack for t in tenants}

    inbound = (
        InboundEvent.objects.using("owner")
        .filter(tenant_id__in=ids, kind="message", received_at__gte=start)
        .count()
    )
    outbound_qs = OutboundMessage.objects.using("owner").filter(
        tenant_id__in=ids, status="sent", sent_at__gte=start
    )
    outbound = outbound_qs.count()
    users = outbound_qs.values("contact_id").distinct().count()
    billable_qs = OutboundMessage.objects.using("owner").filter(
        tenant_id__in=ids, billable=True, sent_at__gte=start
    )
    billable = billable_qs.count()

    by_tenant_prices: dict[UUID, dict[str | None, int]] = defaultdict(dict)
    for row in billable_qs.values("tenant_id", "pricing_category").annotate(total=Count("id")):
        by_tenant_prices[row["tenant_id"]][row["pricing_category"]] = row["total"]
    # Per-tenant costs, already rounded, summed — so the Clientes table adds up.
    cost_eur = sum((costs.cost_of(counts) for counts in by_tenant_prices.values()), Decimal(0))

    inbound_by_day: dict[date, int] = dict(
        InboundEvent.objects.using("owner")
        .filter(tenant_id__in=ids, kind="message", received_at__gte=start)
        .annotate(day=TruncDate("received_at", tzinfo=MADRID))
        .values("day")
        .annotate(total=Count("id"))
        .values_list("day", "total")
    )
    outbound_by_day: dict[date, int] = dict(
        outbound_qs.annotate(day=TruncDate("sent_at", tzinfo=MADRID))
        .values("day")
        .annotate(total=Count("id"))
        .values_list("day", "total")
    )
    days = sorted(set(inbound_by_day) | set(outbound_by_day))
    by_day = [
        DayCount(date=day, inbound=inbound_by_day.get(day, 0), outbound=outbound_by_day.get(day, 0))
        for day in days
    ]

    metric_totals: dict[tuple[str, str], Decimal] = defaultdict(Decimal)
    for row in (
        MetricEvent.objects.using("owner")
        .filter(tenant_id__in=ids, created_at__gte=start)
        .values("tenant_id", "kind")
        .annotate(total=Sum("value"))
    ):
        pack = pack_by_id.get(row["tenant_id"])
        if pack is not None:
            metric_totals[(pack, row["kind"])] += row["total"]
    metrics = [
        MetricTotal(pack=pack, kind=kind, label=METRIC_LABELS.get(kind, kind), total=total)
        for (pack, kind), total in sorted(metric_totals.items())
    ]

    return start, _GlobalMonth(
        inbound=inbound,
        outbound=outbound,
        users=users,
        billable=billable,
        cost_eur=cost_eur,
        by_day=by_day,
        metrics=metrics,
    )


def _recent_alerts() -> list[AlertBrief]:
    alerts = OpsAlert.objects.using("owner").order_by("-last_seen_at")[:MAX_RECENT_ALERTS]
    by_id = {t.id: t.slug for t in get_registry().tenants}
    return [
        AlertBrief(
            id=alert.id,
            kind=alert.kind,
            tenant=by_id.get(alert.tenant_id) if alert.tenant_id else None,
            severity=alert.severity,
            text=alert.text,
            occurred_at=alert.last_seen_at,
            resolved=alert.resolved_at is not None,
        )
        for alert in alerts
    ]


def build_overview(now: datetime | None = None) -> Overview:
    now = now or timezone.now()
    tenants = _active_tenants()
    rows = tenant_rows(now)
    open_alerts = _open_alerts()
    start, month = _global_month(now, tenants)

    backup = system.read_backup_status(settings.OPS_STATE_DIR)
    deploys = system.read_deploys(settings.OPS_STATE_DIR, limit=1)
    deployed_at = None
    if deploys:
        try:
            deployed_at = datetime.fromisoformat(deploys[-1]["at"])
        except KeyError, ValueError:
            deployed_at = None
    last_backup_at = None
    backup_ok = None
    if backup is not None:
        backup_ok = backup.get("ok")
        try:
            last_backup_at = datetime.fromisoformat(backup["finished_at"])
        except KeyError, ValueError:
            last_backup_at = None

    stale_outbound = _stale_outbound(now, [t.id for t in tenants])
    incidents_open = len(open_alerts) + stale_outbound + _failed_jobs()

    by_slug = {t.id: t.slug for t in tenants}
    if (
        any(a.severity == "critical" for a in open_alerts)
        or any(r.health == "critical" for r in rows)
        or stale_outbound > 0
    ):
        level: Literal["ok", "warning", "critical"] = "critical"
    elif any(a.severity == "warning" for a in open_alerts) or any(
        r.health == "warning" for r in rows
    ):
        level = "warning"
    else:
        level = "ok"

    problems: list[ProblemBrief] = []
    for alert in sorted(
        open_alerts, key=lambda a: (a.severity != "critical", -a.last_seen_at.timestamp())
    ):
        if alert.severity not in ("critical", "warning"):
            continue
        slug = by_slug.get(alert.tenant_id) if alert.tenant_id else None
        problems.append(
            ProblemBrief(text=alert.text, tenant=slug, link=f"/clientes/{slug}" if slug else None)
        )
    for row in rows:
        if row.health in ("critical", "warning"):
            problems.extend(
                ProblemBrief(
                    text=f"{row.slug}: {reason}", tenant=row.slug, link=f"/clientes/{row.slug}"
                )
                for reason in row.health_reasons
            )
    problems = problems[:MAX_PROBLEMS]

    return Overview(
        generated_at=now,
        status=StatusBlock(level=level, problems=problems),
        tenants=_tenant_counts(tenants),
        month=MonthSummary(
            start=start,
            inbound=month.inbound,
            outbound=month.outbound,
            users=month.users,
            billable=month.billable,
            cost_eur=month.cost_eur,
            by_day=month.by_day,
            metrics=month.metrics,
        ),
        tenant_rows=rows,
        incidents_open=incidents_open,
        system=SystemBrief(
            cpu_pct=system.cpu_percent(),
            mem_used_pct=system.memory(),
            disk_used_pct=system.disk(),
            last_backup_at=last_backup_at,
            backup_ok=backup_ok,
            tls_days_left=None,
            release=settings.RELEASE_SHA,
            deployed_at=deployed_at,
        ),
        recent_alerts=_recent_alerts(),
    )
