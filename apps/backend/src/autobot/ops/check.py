"""Five-minute worker checks; external calls happen after tenant transactions."""

import logging
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from statistics import median
from uuid import UUID

import httpx
from django.conf import settings
from django.core.cache import cache
from django.db import connection
from django.db.models import Q
from django.utils import timezone

from autobot.channels.demo.doors import door
from autobot.channels.telegram.polling import DEMO_WEBHOOK_PATH, NOTIFY_WEBHOOK_PATH
from autobot.channels.telegram.registration import expected_webhook_url
from autobot.ops import containers, health, queues, state, system
from autobot.ops.models import OpsAlert, SystemSample
from autobot.owner import links
from autobot.runtime.cache import auth_flag_key
from autobot.runtime.models import (
    DEMO_CHANNELS,
    Channel,
    InboundEvent,
    Notification,
    OutboundMessage,
)
from autobot.runtime.notifications import bot_secrets, resolve_alert, send_ops_alert
from autobot.runtime.outbound import RECONCILE_WAIT
from autobot.runtime.periodic import channels_for
from autobot.runtime.sweeps import SweepResult, sweep_tenant
from autobot.tenancy.registry import LoadedTenant, get_registry
from autobot.tenancy.tx import tenant_tx

SAMPLE_RETENTION = timedelta(days=62)
DISK_WARNING_PCT = 80
DISK_CRITICAL_PCT = 95
# The operator prunes the backup repository by hand (ADR-021); ops_check alerts when the
# last prune (a marker snapshot, read by backup.sh into backup-prune.json) is older.
PRUNE_OVERDUE = timedelta(days=10)

CHECK_FAILED = "check_failed"

# `tenant_silent`: no customer message for max(SILENT_MIN, SILENT_GAP_FACTOR x the median
# gap between its messages over the last SILENT_WINDOW). 48 h so a business closed for the
# weekend does not alert on Monday morning; business hours are not modelled.
SILENT_MIN = timedelta(hours=48)
SILENT_WINDOW = timedelta(days=14)
SILENT_GAP_FACTOR = 3
SILENT_MIN_HISTORY = 5  # messages seen; a new tenant (or a tester's one) never alerts

# Health issue codes of a tenant that are alerts of their own, not `health:<code>`.
HEALTH_KINDS = {
    "webhook_unsubscribed": "webhook_unsubscribed",
    "number_quality": "number_quality",
    "telegram_webhook_unregistered": "webhook_unsubscribed",
    "telegram_webhook": "webhook_errors",
    "telegram_webhook_backlog": "webhook_errors",
}

# Seconds of external health checks (Meta, Telegram, Google, one after another) one run may
# spend; the tenants still due are checked on the next runs, the most overdue first.
HEALTH_BUDGET_S = 60.0

# A provider-wide outage (Meta, Telegram or Google) is one alert, not one per tenant. The
# per-tenant alerts it causes are held back while it lasts and for OUTAGE_GRACE after, the
# time the tenants' cached health results (RETRY_FAILED_S) take to be refreshed. Google
# has no breaker signal shared between processes: it is an outage when at least
# GOOGLE_OUTAGE_MIN calendar tenants, and GOOGLE_OUTAGE_RATIO of them, report Calendar
# trouble in the same run. A few tenants (one broken calendar share) alert on their own.
OUTAGE_GRACE = timedelta(minutes=20)
GOOGLE_OUTAGE_MIN = 5
GOOGLE_OUTAGE_RATIO = 0.3
CALENDAR_OUTAGE = "calendar_outage"
PROVIDER_HEALTH_KINDS = {
    "whatsapp": "health:whatsapp_unavailable",
    "telegram": "health:telegram_unavailable",
}

DEMO_LABELS = {Channel.DEMO_TG: "Telegram", Channel.DEMO_WA: "WhatsApp"}

log = logging.getLogger(__name__)


def _sweep(tenant: LoadedTenant, now: datetime) -> SweepResult:
    """The stuck-work sweeps of one tenant; a failing one never stops the check."""
    try:
        return sweep_tenant(tenant, now)
    except Exception:
        log.exception("sweep of tenant %s failed", tenant.slug)
        return SweepResult()


def silent_threshold(received: list[datetime]) -> timedelta:
    """`received`: message times, newest first, within the window."""
    gaps = [(a - b).total_seconds() for a, b in zip(received, received[1:], strict=False)]
    if not gaps:
        return SILENT_MIN
    return max(SILENT_MIN, SILENT_GAP_FACTOR * timedelta(seconds=median(gaps)))


def _is_silent(now: datetime) -> bool:
    """Inside a tenant transaction: an indexed read of the main channel's messages."""
    messages = InboundEvent.objects.filter(channel=Channel.MAIN, kind=InboundEvent.Kind.MESSAGE)
    # Every five minutes for every tenant: the common case (a message within SILENT_MIN,
    # the threshold's floor) costs one indexed row, never the whole window.
    last_seen = messages.order_by("-received_at").values_list("received_at", flat=True).first()
    if last_seen is None or now - last_seen <= SILENT_MIN:
        return False
    recent = list(
        messages.filter(received_at__gte=now - SILENT_WINDOW)
        .order_by("-received_at")
        .values_list("received_at", flat=True)[:2000]
    )
    if recent:
        last = recent[0]
        history = len(recent)
    else:
        older = list(messages.order_by("-received_at").values_list("received_at", flat=True)[:5])
        if not older:
            return False
        last, history = older[0], len(older)
    if history < SILENT_MIN_HISTORY:
        return False
    return now - last > silent_threshold(recent)


@dataclass(frozen=True)
class Finding:
    kind: str
    tenant_id: UUID | None
    text: str
    # Explained by a platform-wide outage that has its own alert (see `_suppress_outages`):
    # not raised, and an open alert of the same key is resolved without a message.
    suppressed: bool = False


def _check_tenant(
    tenant: LoadedTenant,
    now: datetime,
    out: list[Finding],
    budget: health.HealthBudget | None = None,
) -> int:
    """The findings of one tenant, appended to `out`; returns its demo WhatsApp billables."""
    demo_wa_billable = 0
    if tenant.document.status == "offboarded":
        return 0
    pending: list[tuple[str, str]] = []
    if tenant.is_degraded or (not tenant.is_demo and not tenant.main_enabled):
        pending.append(
            ("tenant_unavailable", "🔴 Tenant degradado o canal sin secretos/configuración.")
        )
    sweep = _sweep(tenant, now)
    if sweep.outbound_unknown or sweep.outbound_stuck:
        pending.append(
            (
                "outbound_stuck",
                "🟠 Envíos atascados sin trabajo (ambiguos o demasiado antiguos para reencolar).",
            )
        )
    if sweep.inbound_stuck:
        pending.append(
            (
                "inbound_stuck",
                "🔴 Eventos entrantes pendientes sin trabajo desde hace más de 5 minutos"
                f" ({sweep.inbound_requeued} reencolados).",
            )
        )
    with tenant_tx(tenant.id):
        if (
            tenant.document.status == "active"
            and not tenant.is_demo
            and tenant.main_enabled
            and _is_silent(now)
        ):
            pending.append(
                (
                    "tenant_silent",
                    "🟠 Sin mensajes de clientes desde hace más de lo habitual: revisa que"
                    " el canal sigue conectado.",
                )
            )
        messages = OutboundMessage.objects.all()
        # Messages already unknown before this version have no transition time.
        # First observation establishes a conservative lower bound, never creation.
        messages.filter(status="unknown", unknown_at__isnull=True).update(unknown_at=now)
        day_ago = now - timedelta(hours=24)
        if messages.filter(
            Q(status="failed", created_at__gte=day_ago)
            | Q(
                status="unknown",
                # Still unknown after the wait for a status and the reconcile that follows
                # (ADR-026): neither resolved it, a person must.
                unknown_at__lt=now - RECONCILE_WAIT - timedelta(minutes=10),
                unknown_at__gte=day_ago,
            )
        ).exists():
            pending.append(
                (
                    "outbound_failed",
                    "🟠 Hay envíos fallidos o ambiguos que la conciliación automática no resolvió.",
                )
            )
        # A notice is claimed `failed` before the provider is called and an ambiguous
        # result stays so (never resent blindly). With the owner chat and the bot
        # configured, a recent failed one was a rejected or ambiguous delivery. An
        # `expired` one (still undelivered after NOTICE_TTL, i.e. the bot was unreachable
        # for hours; a rate-limit backlog drains in seconds) is a lost notice too, and
        # rare enough not to be noise.
        if (
            bot_secrets() is not None
            and links.owner_chat(tenant.id) is not None
            and Notification.objects.filter(
                status__in=(Notification.Status.FAILED, Notification.Status.EXPIRED),
                created_at__gte=day_ago,
            ).exists()
        ):
            pending.append(
                (
                    "notification_failed",
                    "🟠 Hay avisos al dueño fallidos, ambiguos o caducados en las últimas 24 h.",
                )
            )
        # Notices held because the owner never linked a chat are not failures (they go out
        # when they link), but a real business whose owner hears nothing needs a nudge.
        if (
            not tenant.is_demo
            and tenant.document.status == "active"
            and Notification.objects.filter(
                status=Notification.Status.HELD, created_at__gte=day_ago
            ).exists()
        ):
            pending.append(
                (
                    "owner_unlinked",
                    "🟡 Hay avisos retenidos: el dueño no ha conectado su chat de avisos.",
                )
            )
        # A demo-door rejection belongs to the platform's own credentials, not the
        # tenant's configured main-channel credentials.
        auth_channels = list(
            messages.filter(last_error__startswith="auth:")
            .values_list("channel", flat=True)
            .distinct()
        )
        channel = tenant.document.channel
        if channel is not None and channel.type == "whatsapp":
            local_now = now.astimezone(tenant.info.timezone)
            start = local_now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            count = messages.filter(channel=Channel.MAIN, billable=True, sent_at__gte=start).count()
            if count > channel.monthly_alert_threshold:
                pending.append(
                    (
                        "billing",
                        "🟡 Mensajes facturables de WhatsApp por encima del umbral mensual.",
                    )
                )
        if tenant.is_demo:
            local_now = now.astimezone(tenant.info.timezone)
            start = local_now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            demo_wa_billable += messages.filter(
                channel=Channel.DEMO_WA, billable=True, sent_at__gte=start
            ).count()
    for auth_channel in auth_channels:
        demo = auth_channel in DEMO_CHANNELS
        out.append(
            Finding(
                f"auth:{auth_channel}" if demo else "auth",
                None if demo else tenant.id,
                f"🔴 Bot de demo ({DEMO_LABELS.get(Channel(auth_channel), auth_channel)}):"
                " envío rechazado por autenticación."
                if demo
                else "🔴 Envío del canal principal rechazado por autenticación.",
            )
        )
    for bound_channel in channels_for(tenant):
        signal = state.read(tenant.id, bound_channel)
        if signal.get("calendar_unavailable") or signal.get("calendar_errors", 0) >= 3:
            pending.append(
                (
                    f"calendar:{bound_channel}",
                    "🔴 Calendar sin acceso o con tres errores seguidos.",
                )
            )
        if signal.get("errors", 0) >= 3:
            pending.append(
                (f"errors:{bound_channel}", "🔴 El tenant acumula tres errores seguidos.")
            )
        if tenant.pack and any(p.name == "calendar_sweep" for p in tenant.pack.periodic):
            baseline = state.sweep_baseline(tenant.id, bound_channel, now)
            if now - baseline > timedelta(hours=1):
                pending.append(
                    (
                        f"sweep:{bound_channel}",
                        "🟠 Barrido sin completarse desde hace más de una hora.",
                    )
                )
    issues = health.daily(tenant.id, lambda t=tenant: health.tenant_health(t), budget=budget)
    for issue in issues:
        kind = HEALTH_KINDS.get(issue.code, f"health:{issue.code}")
        pending.append((kind, f"{issue.severity} {issue.message}"))
    for kind, text in pending:
        out.append(Finding(kind, tenant.id, f"{tenant.slug}: {text}"))
    return demo_wa_billable


def _queue_lag_findings(lags: list[queues.QueueLag], now: datetime) -> list[Finding]:
    out: list[Finding] = []
    for lag in lags:
        waiting = lag.ready_age_s(now)
        running = lag.running_age_s(now)
        limit = queues.LAG_THRESHOLD_S.get(lag.queue_name)
        stuck = queues.STUCK_S.get(lag.queue_name, queues.DEFAULT_STUCK_S)
        reasons = []
        if limit is not None and waiting is not None and waiting > limit:
            reasons.append(f"trabajo listo esperando {waiting / 60:.0f} min (límite {limit // 60})")
        if running is not None and running > stuck:
            reasons.append(f"trabajo en curso desde hace {running / 60:.0f} min")
        if reasons:
            out.append(
                Finding(
                    f"queue_lag:{lag.queue_name}",
                    None,
                    f"🟠 Cola {lag.queue_name} atrasada: {'; '.join(reasons)}.",
                )
            )
    return out


def _google_signal(kind: str) -> bool:
    """A per-tenant finding that says Google Calendar is failing for it."""
    return kind.startswith("calendar:") or (
        kind.startswith("health:") and kind.endswith(":calendar_unavailable")
    )


@dataclass(frozen=True)
class OutageScope:
    """Which per-tenant alert kinds a provider-wide outage explains right now."""

    provider_kinds: frozenset[str]
    google: bool  # Calendar failing for many tenants, or just recovered
    google_down: bool
    affected: int
    calendar_tenants: int

    def explains(self, kind: str) -> bool:
        return kind in self.provider_kinds or (
            self.google and (_google_signal(kind) or kind.startswith("errors:"))
        )


def outage_scope(
    findings: list[Finding], tenants: list[LoadedTenant], now: datetime
) -> OutageScope:
    provider_kinds = frozenset(
        PROVIDER_HEALTH_KINDS[p]
        for p in {*state.providers_down(now), *state.providers_recovering(now, OUTAGE_GRACE)}
    )
    calendar_tenants = sum(
        1
        for t in tenants
        if t.pack is not None
        and t.pack.needs_calendar
        and not t.is_degraded
        and t.document.status != "offboarded"
    )
    affected = len({f.tenant_id for f in findings if f.tenant_id and _google_signal(f.kind)})
    google_down = affected >= GOOGLE_OUTAGE_MIN and affected >= (
        GOOGLE_OUTAGE_RATIO * calendar_tenants
    )
    recovering = (
        not google_down
        and OpsAlert.objects.filter(
            Q(resolved_at__isnull=True) | Q(resolved_at__gte=now - OUTAGE_GRACE),
            kind=CALENDAR_OUTAGE,
        ).exists()
    )
    return OutageScope(
        provider_kinds, google_down or recovering, google_down, affected, calendar_tenants
    )


def _suppress_outages(
    findings: list[Finding], tenants: list[LoadedTenant], now: datetime
) -> list[Finding]:
    """One alert for a provider-wide outage instead of one per tenant: adds
    `calendar_outage` when Google is failing for many tenants, and flags as `suppressed`
    the per-tenant findings that the Meta, Telegram or Google outage explains."""
    scope = outage_scope(findings, tenants, now)
    out = [
        replace(f, suppressed=True) if f.tenant_id is not None and scope.explains(f.kind) else f
        for f in findings
    ]
    if scope.google_down:
        out.append(
            Finding(
                CALENDAR_OUTAGE,
                None,
                f"🔴 Google Calendar falla en {scope.affected} de {scope.calendar_tenants}"
                " negocios con calendario: las reservas se reintentan solas; las alertas por"
                " negocio quedan agrupadas en esta.",
            )
        )
    return out


def collect() -> list[Finding]:
    findings: list[Finding] = []
    now = timezone.now()
    # Query the platform tables as fp_app: no customer data and no owner bypass.
    with connection.cursor() as cursor:
        lags = queues.queue_lags(cursor, now)
        cursor.execute(
            """SELECT EXISTS(SELECT 1 FROM procrastinate_events e
            JOIN procrastinate_jobs j ON j.id = e.job_id
            WHERE e.type = 'failed' AND e.at >= %s AND j.status = 'failed')""",
            [now - timedelta(minutes=10)],
        )
        (failed,) = cursor.fetchone() or (False,)
    # One snapshot feeds both: `inbound_delay` (conversations; 🔴) and `queue_lag:<queue>`
    # (everything else, plus running jobs that never finish).
    if any(
        lag.queue_name in queues.INBOUND_QUEUES
        and (age := lag.ready_age_s(now)) is not None
        and age > queues.INBOUND_DELAY_S
        for lag in lags
    ):
        findings.append(
            Finding("inbound_delay", None, "🔴 Trabajo inbound listo desde hace más de 2 minutos.")
        )
    findings.extend(_queue_lag_findings(lags, now))
    if failed:
        findings.append(
            Finding("failed_jobs", None, "🟠 Hay trabajos fallidos en los últimos 10 minutos.")
        )
    down = state.providers_down(now)
    if down:
        findings.append(
            Finding(
                "provider_outage",
                None,
                f"🟠 Proveedor de mensajería caído ({', '.join(down)}): los envíos esperan"
                " y se reintentan solos.",
            )
        )
    registry = get_registry()
    if registry.errors:
        findings.append(
            Finding("registry", None, "🔴 Hay configuraciones de tenants o secretos ilegibles.")
        )
    demo_wa_billable = 0
    # The most overdue health checks first, so what the budget leaves for the next run is
    # what is least late.
    snapshots = health.read_snapshots([t.id for t in registry.tenants])
    budget = health.HealthBudget(HEALTH_BUDGET_S)
    ordered = sorted(
        registry.tenants, key=lambda t: -health.overdue_s(t.id, snapshots.get(t.id), now)
    )
    for tenant in ordered:
        # One tenant's exception must not abort the check of the others nor the heartbeat.
        tenant_findings: list[Finding] = []
        try:
            demo_wa_billable += _check_tenant(tenant, now, tenant_findings, budget)
        except Exception:
            log.exception("check of tenant %s failed", tenant.id)
            tenant_findings.append(
                Finding(
                    CHECK_FAILED,
                    tenant.id,
                    f"{tenant.slug}: 🟠 La comprobación del tenant ha fallado; mira los logs.",
                )
            )
        findings.extend(tenant_findings)
    if budget.skipped:
        log.info("health checks of %s tenants left for the next run (budget spent)", budget.skipped)
    if demo_wa_billable > settings.DEMO_WHATSAPP_MONTHLY_ALERT_THRESHOLD:
        findings.append(
            Finding(
                "billing:demo_wa",
                None,
                "🟡 Mensajes facturables de la puerta WhatsApp de demo por encima del"
                " umbral mensual.",
            )
        )
    for demo_channel, label in DEMO_LABELS.items():
        if cache.get(auth_flag_key(demo_channel)):
            findings.append(
                Finding(
                    f"auth:{demo_channel}",
                    None,
                    f"🔴 Bot de demo ({label}): envío rechazado por autenticación.",
                )
            )
    if cache.get(auth_flag_key("notify")):
        findings.append(
            Finding("bot:notify:auth", None, "🔴 Bot de avisos: envío rechazado por autenticación.")
        )
    for name, token, webhook_path in (
        ("demo_tg", settings.DEMO_TELEGRAM_TOKEN, DEMO_WEBHOOK_PATH),
        ("notify", settings.NOTIFY_BOT_TOKEN, NOTIFY_WEBHOOK_PATH),
    ):
        if token:
            expected = expected_webhook_url(webhook_path)
            issues = health.daily(
                f"bot:{name}",
                lambda token=token, expected=expected: health.telegram_health(
                    token, expected_url=expected
                ),
            )
            for issue in issues:
                findings.append(
                    Finding(
                        f"bot:{name}:{issue.code}",
                        None,
                        f"{issue.severity} Bot {name}: {issue.message}",
                    )
                )
    door_wa = door(Channel.DEMO_WA)
    if door_wa is not None:
        templates = {
            (template.name, template.language)
            for tenant in registry.demo_tenants()
            if tenant.document.status == "active"
            and not tenant.is_degraded
            and tenant.pack is not None
            for template in tenant.pack.templates
        }
        issues = health.daily(
            "bot:demo_wa",
            lambda: health.whatsapp_health(door_wa.description, door_wa.secrets, templates),
        )
        for issue in issues:
            findings.append(
                Finding(
                    f"bot:demo_wa:{issue.code}",
                    None,
                    f"{issue.severity} Bot de demo (WhatsApp): {issue.message}",
                )
            )
    # The container's `/` is the host's Docker filesystem (images, the PostgreSQL volume
    # and the backups' local temp under /srv/autobot/var, which backup.sh needs free for the
    # dump); /run/ops is the bind mount of /srv/autobot/var/state/ops, so it is measured too
    # in case `/srv` is a separate volume: the fullest one counts.
    disk_readings = [
        used
        for used in (system.disk("/"), system.disk(str(settings.OPS_STATE_DIR)))
        if used is not None
    ]
    disk_used_pct = max(disk_readings, default=None)
    if disk_used_pct is not None and disk_used_pct > DISK_CRITICAL_PCT:
        findings.append(Finding("disk_critical", None, "🔴 Disco por encima del 95 %."))
    elif disk_used_pct is not None and disk_used_pct > DISK_WARNING_PCT:
        findings.append(Finding("disk", None, "🟠 Disco por encima del 80 %."))
    if not settings.IS_LOCAL and system.prune_overdue(
        system.read_prune_status(settings.OPS_STATE_DIR), now, PRUNE_OVERDUE
    ):
        findings.append(
            Finding(
                "backup_prune_overdue",
                None,
                "🟡 Hace más de 10 días que no se purgan las copias de seguridad"
                " (`make backup-prune`).",
            )
        )
    # In local there is no containers.sh timer: without this guard every check
    # would report containers_stale.
    if not settings.IS_LOCAL:
        assessment = containers.assess(
            containers.read_snapshot(settings.OPS_STATE_DIR),
            now=now,
            release_sha=settings.RELEASE_SHA,
        )
        findings.extend(Finding(kind, None, text) for kind, text in assessment.findings)
    return _suppress_outages(findings, registry.tenants, now)


def sync_alerts(findings: list[Finding]) -> None:
    now = timezone.now()
    scope = outage_scope(findings, get_registry().tenants, now)
    seen: set[tuple[str, UUID | None]] = set()
    quiet: set[tuple[str, UUID | None]] = set()
    for finding in findings:
        if finding.suppressed:
            quiet.add((finding.kind, finding.tenant_id))
            continue
        send_ops_alert(finding.kind, finding.tenant_id, finding.text)
        seen.add((finding.kind, finding.tenant_id))
    # A tenant whose check failed was only partly evaluated: its other open alerts stay
    # open (neither confirmed nor cleared) until a complete check of it succeeds.
    unchecked = {f.tenant_id for f in findings if f.kind == CHECK_FAILED}
    open_alerts = OpsAlert.objects.filter(resolved_at__isnull=True, auto_resolves=True)
    for alert in open_alerts:
        if alert.tenant_id in unchecked:
            continue
        key = (alert.kind, alert.tenant_id)
        # Explained by an outage with its own alert, even if its finding has just gone
        # (the tenants recover together): resolved without a message of its own.
        if key in quiet or (
            key not in seen and alert.tenant_id is not None and scope.explains(alert.kind)
        ):
            resolve_alert(alert, by="outage", notify=False)
        elif key not in seen:
            resolve_alert(alert, by="auto", notify=alert.severity == "critical")


def take_sample() -> None:
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_database_size(current_database())")
        (db_bytes,) = cursor.fetchone()
    SystemSample.objects.create(
        cpu_pct=system.cpu_percent(),
        mem_used_pct=system.memory(),
        load1=system.load(),
        disk_used_pct=system.disk(),
        db_bytes=db_bytes,
    )
    SystemSample.objects.filter(taken_at__lt=timezone.now() - SAMPLE_RETENTION).delete()


def run() -> None:
    sync_alerts(collect())
    take_sample()
    # No finally: a failed DB/global check must prevent a success heartbeat.
    if settings.HEALTHCHECKS_PING_URL:
        try:
            response = httpx.get(settings.HEALTHCHECKS_PING_URL, timeout=10)
            if not response.is_success:
                log.warning("healthchecks heartbeat rejected (HTTP %s)", response.status_code)
        except httpx.HTTPError:
            log.warning("healthchecks heartbeat unavailable")
