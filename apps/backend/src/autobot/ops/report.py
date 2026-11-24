"""The platform's state for the operator, as plain data (ADR-029): what the operator
menu of the notify bot and its daily summary tell. `report_text` turns it into text, so
the figures and their wording change apart.

It runs in the workers, as `fp_app`: platform tables (`ops_alert`, `system_sample`,
`procrastinate_jobs`) are read directly, and a tenant's own figures only inside its
`tenant_tx`, one tenant at a time (RLS). No personal data leaves this module: only
counts, states and the business names."""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db import connection
from django.db.models import Max

from autobot.ops import containers, health, system
from autobot.ops.check import BACKUP_STALE, PRUNE_OVERDUE, SAMPLE_MAX_AGE
from autobot.ops.models import OpsAlert, SystemSample
from autobot.ops.status import tenant_status
from autobot.runtime.models import Contact, InboundEvent, OutboundMessage
from autobot.tenancy.registry import LoadedTenant, get_registry
from autobot.tenancy.tx import tenant_tx

# The operator's day: the figures of "Hoy" and the daily summary use this zone.
MADRID = ZoneInfo("Europe/Madrid")

type Level = Literal["ok", "notice", "warning", "critical"]
_LEVELS: tuple[Level, ...] = ("ok", "notice", "warning", "critical")  # least to most severe
_RANK: dict[str, int] = {level: rank for rank, level in enumerate(_LEVELS)}
_FAILED = (OutboundMessage.Status.FAILED, OutboundMessage.Status.EXPIRED)


def worst(levels: list[str]) -> Level:
    """The most severe of `levels`; anything else (`info`, `unknown`) counts as ok."""
    return _LEVELS[max((_RANK.get(level, 0) for level in levels), default=0)]


# ── Status ──────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class AlertLine:
    severity: str  # critical | warning | notice | info
    text: str  # as the alert was sent: starts with its emoji (and the slug, per tenant)
    since: datetime


@dataclass(frozen=True)
class Services:
    """From the containers snapshot of the host (`autobot-containers.timer`)."""

    running: int
    total: int
    stale: bool  # the snapshot is older than its timer allows
    failing: list[str]  # services not ok


@dataclass(frozen=True)
class Resources:
    """The last sample of `ops_check` (every 5 minutes)."""

    taken_at: datetime
    disk_pct: float | None
    mem_pct: float | None
    db_bytes: int


@dataclass(frozen=True)
class Backups:
    """From `backup.json` and `backup-prune.json`, written by `backup.sh`. `None` fields:
    the file is not there (a server that has not backed up yet, or local)."""

    finished_at: datetime | None
    ok: bool | None
    stale: bool  # failed, or no backup finished within BACKUP_STALE
    last_prune_at: datetime | None
    prune_overdue: bool


@dataclass(frozen=True)
class Cleanup:
    """The last nightly `retention_cleanup` job, if the queue still keeps it."""

    enabled: bool
    last_at: datetime | None
    ok: bool | None  # None: queued or running


@dataclass(frozen=True)
class PlatformStatus:
    level: Level
    alerts: list[AlertLine]  # open ones, most severe and most recent first
    services: Services | None
    resources: Resources | None
    backups: Backups
    cleanup: Cleanup
    troubled: list[str]  # names of the tenants whose health is warning or critical


def platform_status(now: datetime) -> PlatformStatus:
    alerts = open_alerts()
    tenants = tenant_lines(now, with_activity=False)
    return PlatformStatus(
        level=worst([*(a.severity for a in alerts), *(t.level for t in tenants)]),
        alerts=alerts,
        troubled=[t.name for t in tenants if t.level in ("warning", "critical")],
        services=_services(now),
        resources=_resources(now),
        backups=backups(now),
        cleanup=cleanup(),
    )


def open_alerts() -> list[AlertLine]:
    rows = OpsAlert.objects.filter(resolved_at__isnull=True)
    lines = [AlertLine(a.severity, a.text, a.first_seen_at) for a in rows]
    return sorted(lines, key=lambda a: (-_RANK.get(a.severity, 0), -a.since.timestamp()))


def _services(now: datetime) -> Services | None:
    snapshot = containers.read_snapshot(settings.OPS_STATE_DIR)
    if snapshot is None:
        return None
    assessment = containers.assess(snapshot, now=now, release_sha=settings.RELEASE_SHA)
    rows = assessment.services
    return Services(
        running=sum(row.status == "running" for row in rows),
        total=len(rows),
        stale=assessment.stale,
        failing=[row.service for row in rows if row.level in ("warning", "critical")],
    )


def _resources(now: datetime) -> Resources | None:
    sample = SystemSample.objects.order_by("-taken_at").first()
    if sample is None or now - sample.taken_at > SAMPLE_MAX_AGE:
        return None
    return Resources(
        taken_at=sample.taken_at,
        disk_pct=sample.disk_used_pct,
        mem_pct=sample.mem_used_pct,
        db_bytes=sample.db_bytes,
    )


def backups(now: datetime) -> Backups:
    status = system.read_backup_status(settings.OPS_STATE_DIR)
    prune = system.read_prune_status(settings.OPS_STATE_DIR)
    finished = system.parse_time(status.get("finished_at")) if status else None
    ok = status.get("ok") if status else None
    return Backups(
        finished_at=finished,
        ok=ok if isinstance(ok, bool) else None,
        stale=status is not None
        and (ok is False or finished is None or now - finished > BACKUP_STALE),
        last_prune_at=system.parse_time(prune.get("last_prune_at")) if prune else None,
        prune_overdue=system.prune_overdue(prune, now, PRUNE_OVERDUE),
    )


def cleanup() -> Cleanup:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT status, scheduled_at FROM procrastinate_jobs"
            " WHERE task_name = 'retention_cleanup' ORDER BY id DESC LIMIT 1"
        )
        row = cursor.fetchone()
    if row is None:
        return Cleanup(enabled=settings.RETENTION_CLEANUP_ENABLED, last_at=None, ok=None)
    status, scheduled_at = row
    ok = {"succeeded": True, "failed": False}.get(status)
    return Cleanup(enabled=settings.RETENTION_CLEANUP_ENABLED, last_at=scheduled_at, ok=ok)


# ── Tenants ─────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class TenantLine:
    name: str
    slug: str
    demo: bool
    status: str  # the document's: onboarding | active | paused
    level: Level  # its health, as the panel shows it ("unknown" counts as ok here)
    reasons: list[str]
    last_activity_at: datetime | None


def tenant_lines(now: datetime, *, with_activity: bool = True) -> list[TenantLine]:
    """Every tenant not offboarded, by name. `with_activity` adds the time of its last
    message, one `tenant_tx` per tenant."""
    tenants = _tenants()
    alerts = list(OpsAlert.objects.filter(resolved_at__isnull=True, tenant_id__isnull=False))
    snapshots = health.read_snapshots([t.id for t in tenants])
    lines = []
    for tenant in tenants:
        status = tenant_status(tenant, open_alerts=alerts, snapshots=snapshots)
        level: Level = "ok" if status.level == "unknown" else status.level
        lines.append(
            TenantLine(
                name=tenant.info.name,
                slug=tenant.slug,
                demo=tenant.is_demo,
                status=tenant.document.status,
                level=level,
                reasons=status.reasons if level != "ok" else [],
                last_activity_at=_last_activity(tenant.id) if with_activity else None,
            )
        )
    return lines


def _tenants() -> list[LoadedTenant]:
    tenants = [t for t in get_registry().tenants if t.document.status != "offboarded"]
    return sorted(tenants, key=lambda t: t.info.name.lower())


def _last_activity(tenant_id: UUID) -> datetime | None:
    with tenant_tx(tenant_id):
        received = InboundEvent.objects.aggregate(at=Max("received_at"))["at"]
        sent = OutboundMessage.objects.filter(status=OutboundMessage.Status.SENT).aggregate(
            at=Max("sent_at")
        )["at"]
    return max((at for at in (received, sent) if at is not None), default=None)


# ── A day's figures ─────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Figures:
    received: int = 0  # messages from contacts
    sent: int = 0  # messages that went out
    failed: int = 0  # sends that failed or expired
    new_contacts: int = 0

    def __add__(self, other: Figures) -> Figures:
        return Figures(
            self.received + other.received,
            self.sent + other.sent,
            self.failed + other.failed,
            self.new_contacts + other.new_contacts,
        )

    @property
    def empty(self) -> bool:
        return self == Figures()


@dataclass(frozen=True)
class TenantFigures:
    name: str
    demo: bool
    figures: Figures


@dataclass(frozen=True)
class Day:
    start: datetime
    end: datetime
    tenants: list[TenantFigures] = field(default_factory=list)

    @property
    def total(self) -> Figures:
        return sum((t.figures for t in self.tenants), Figures())

    @property
    def real(self) -> list[TenantFigures]:
        """Real tenants with any figure, busiest first."""
        busy = [t for t in self.tenants if not t.demo and not t.figures.empty]
        return sorted(busy, key=lambda t: (-t.figures.received, -t.figures.sent, t.name))

    @property
    def demos(self) -> Figures:
        return sum((t.figures for t in self.tenants if t.demo), Figures())


def day_bounds(now: datetime, *, days_ago: int = 0) -> tuple[datetime, datetime]:
    """Madrid's day `days_ago` days before today's: from its midnight to the next one,
    or to `now` for today."""
    # Arithmetic on a ZoneInfo datetime is wall-clock: a day across a DST change is
    # still midnight to midnight.
    midnight = now.astimezone(MADRID).replace(hour=0, minute=0, second=0, microsecond=0)
    start = midnight - timedelta(days=days_ago)
    return (start, now) if days_ago == 0 else (start, start + timedelta(days=1))


def day_figures(start: datetime, end: datetime) -> Day:
    return Day(
        start=start,
        end=end,
        tenants=[
            TenantFigures(t.info.name, t.is_demo, _figures(t.id, start, end)) for t in _tenants()
        ],
    )


def _figures(tenant_id: UUID, start: datetime, end: datetime) -> Figures:
    with tenant_tx(tenant_id):
        received = InboundEvent.objects.filter(
            kind=InboundEvent.Kind.MESSAGE, received_at__gte=start, received_at__lt=end
        ).count()
        sent = OutboundMessage.objects.filter(
            status=OutboundMessage.Status.SENT, sent_at__gte=start, sent_at__lt=end
        ).count()
        failed = OutboundMessage.objects.filter(
            status__in=_FAILED, created_at__gte=start, created_at__lt=end
        ).count()
        new_contacts = Contact.objects.filter(created_at__gte=start, created_at__lt=end).count()
    return Figures(received, sent, failed, new_contacts)
