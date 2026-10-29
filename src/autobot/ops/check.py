"""Five-minute worker checks; external calls happen after tenant transactions."""

import logging
import shutil
from datetime import timedelta

import httpx
from django.conf import settings
from django.core.cache import cache
from django.db import connection
from django.db.models import Q
from django.utils import timezone

from autobot.channels.demo.doors import door
from autobot.ops import health, state
from autobot.runtime.models import DEMO_CHANNELS, Channel, OutboundMessage
from autobot.runtime.notifications import send_ops_alert
from autobot.runtime.periodic import channels_for
from autobot.tenancy.registry import get_registry
from autobot.tenancy.tx import tenant_tx

DEMO_LABELS = {Channel.DEMO_TG: "Telegram", Channel.DEMO_WA: "WhatsApp"}

log = logging.getLogger(__name__)


def run() -> None:
    now = timezone.now()
    # Query the platform tables as fp_app: no customer data and no owner bypass.
    with connection.cursor() as cursor:
        cursor.execute(
            """SELECT EXISTS(SELECT 1 FROM procrastinate_jobs
            WHERE queue_name = 'inbound' AND status = 'todo'
            AND (scheduled_at < %s OR (scheduled_at IS NULL AND
            (SELECT MAX(at) FROM procrastinate_events WHERE job_id = procrastinate_jobs.id
             AND type IN ('deferred', 'deferred_for_retry', 'scheduled')) < %s))),
            EXISTS(SELECT 1 FROM procrastinate_events e
            JOIN procrastinate_jobs j ON j.id = e.job_id
            WHERE e.type = 'failed' AND e.at >= %s AND j.status = 'failed')""",
            [now - timedelta(minutes=2), now - timedelta(minutes=2), now - timedelta(minutes=10)],
        )
        oldest, failed = cursor.fetchone() or (False, False)
    if oldest:
        send_ops_alert(
            "inbound_delay", None, "🔴 Trabajo inbound listo desde hace más de 2 minutos."
        )
    if failed:
        send_ops_alert("failed_jobs", None, "🟠 Hay trabajos fallidos en los últimos 10 minutos.")
    registry = get_registry()
    if registry.errors or registry.secrets_error:
        send_ops_alert("registry", None, "🔴 Hay configuraciones de tenants o secretos ilegibles.")
    demo_wa_billable = 0
    for tenant in registry.tenants:
        if tenant.file.status == "offboarded":
            continue
        pending: list[tuple[str, str]] = []
        if tenant.is_degraded or (not tenant.is_demo and not tenant.main_enabled):
            pending.append(
                ("tenant_unavailable", "🔴 Tenant degradado o canal sin secretos/configuración.")
            )
        with tenant_tx(tenant.id):
            messages = OutboundMessage.objects.all()
            # Messages already unknown before this version have no transition time.
            # First observation establishes a conservative lower bound, never creation.
            messages.filter(status="unknown", unknown_at__isnull=True).update(unknown_at=now)
            if messages.filter(
                Q(status="failed") | Q(status="unknown", unknown_at__lt=now - timedelta(minutes=10))
            ).exists():
                pending.append(
                    (
                        "outbound_failed",
                        "🟠 Hay envíos fallidos o ambiguos desde hace más de 10 minutos.",
                    )
                )
            # A demo-door rejection belongs to the platform's own credentials, not the
            # tenant's configured main-channel credentials.
            auth_channels = list(
                messages.filter(last_error__startswith="auth:")
                .values_list("channel", flat=True)
                .distinct()
            )
            channel = tenant.file.channel
            if channel is not None and channel.type == "whatsapp":
                local_now = now.astimezone(tenant.info.timezone)
                start = local_now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
                count = messages.filter(
                    channel=Channel.MAIN, billable=True, sent_at__gte=start
                ).count()
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
            send_ops_alert(
                f"auth:{auth_channel}" if demo else "auth",
                None if demo else tenant.id,
                f"🔴 Bot de demo ({DEMO_LABELS.get(Channel(auth_channel), auth_channel)}):"
                " envío rechazado por autenticación."
                if demo
                else "🔴 Envío del canal principal rechazado por autenticación.",
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
        issues = health.daily(tenant.id, lambda t=tenant: health.tenant_health(t))
        for issue in issues:
            pending.append((f"health:{issue.code}", f"{issue.severity} {issue.message}"))
        for kind, text in pending:
            send_ops_alert(kind, tenant.id, f"{tenant.slug}: {text}")
    if demo_wa_billable > settings.DEMO_WHATSAPP_MONTHLY_ALERT_THRESHOLD:
        send_ops_alert(
            "billing:demo_wa",
            None,
            "🟡 Mensajes facturables de la puerta WhatsApp de demo por encima del umbral mensual.",
        )
    for demo_channel, label in DEMO_LABELS.items():
        if cache.get(f"bot:{demo_channel}:auth"):
            send_ops_alert(
                f"auth:{demo_channel}",
                None,
                f"🔴 Bot de demo ({label}): envío rechazado por autenticación.",
            )
    if cache.get("bot:notify:auth"):
        send_ops_alert(
            "bot:notify:auth", None, "🔴 Bot de avisos: envío rechazado por autenticación."
        )
    for name, token in (
        ("demo_tg", settings.DEMO_TELEGRAM_TOKEN),
        ("notify", settings.NOTIFY_BOT_TOKEN),
    ):
        if token:
            issues = health.daily(f"bot:{name}", lambda token=token: health.telegram_health(token))
            for issue in issues:
                send_ops_alert(
                    f"bot:{name}:{issue.code}",
                    None,
                    f"{issue.severity} Bot {name}: {issue.message}",
                )
    door_wa = door(Channel.DEMO_WA)
    if door_wa is not None:
        templates = {
            (template.name, template.language)
            for tenant in registry.demo_tenants()
            if tenant.file.status == "active" and not tenant.is_degraded and tenant.pack is not None
            for template in tenant.pack.templates
        }
        issues = health.daily(
            "bot:demo_wa",
            lambda: health.whatsapp_health(door_wa.description, door_wa.secrets, templates),
        )
        for issue in issues:
            send_ops_alert(
                f"bot:demo_wa:{issue.code}",
                None,
                f"{issue.severity} Bot de demo (WhatsApp): {issue.message}",
            )
    disk = shutil.disk_usage(settings.BASE_DIR)
    if disk.used / disk.total > 0.85:
        send_ops_alert("disk", None, "🟠 Disco por encima del 85 %.")
    # No finally: a failed DB/global check must prevent a success heartbeat.
    if settings.HEALTHCHECKS_PING_URL:
        try:
            response = httpx.get(settings.HEALTHCHECKS_PING_URL, timeout=10)
            if not response.is_success:
                log.warning("healthchecks heartbeat rejected (HTTP %s)", response.status_code)
        except httpx.HTTPError:
            log.warning("healthchecks heartbeat unavailable")
