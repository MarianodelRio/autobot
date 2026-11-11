"""Fake but realistic panel activity for local development. Every row is
written directly, never through a channel adapter: no external service is ever called.
Everything this command creates is marked (`dev-`/`dev:` prefixes, or a procrastinate
job argument) so `--reset` removes exactly that and nothing else."""

import itertools
import json
import random
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid7

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import connections
from django.utils import timezone

from autobot.ops.containers import EXPECTED_SERVICES
from autobot.ops.models import OpsAlert, SystemSample
from autobot.runtime.models import (
    Channel,
    Contact,
    InboundEvent,
    MetricEvent,
    Notification,
    OutboundMessage,
)
from autobot.tenancy.registry import LoadedTenant, get_registry
from autobot.tenancy.tx import tenant_tx
from core.replies import Text
from core.serialization import dump_outbound

CONTACT_MARKER = "dev-"
ALERT_MARKER = "dev:"
JOB_MARKER = "seed_dev_activity"
PRICING_CATEGORIES = ("utility", "service", "marketing")
SAMPLE_INTERVAL = timedelta(minutes=5)
SAMPLE_WINDOW = timedelta(days=2)
# (kind, tenant-specific, severity, emoji, message, already resolved) — 3 open, 5 resolved.
ALERT_SAMPLES: list[tuple[str, bool, str, str, str, bool]] = [
    ("disk", False, "warning", "🟠", "Disco por encima del 85 %.", False),
    (
        "outbound_failed",
        True,
        "warning",
        "🟠",
        "Envíos fallidos o ambiguos hace más de 10 min.",
        False,
    ),
    (
        "tenant_unavailable",
        True,
        "critical",
        "🔴",
        "Tenant degradado o sin secretos/configuración.",
        False,
    ),
    ("failed_jobs", False, "warning", "🟠", "Trabajos fallidos en los últimos 10 minutos.", True),
    (
        "inbound_delay",
        False,
        "critical",
        "🔴",
        "Trabajo inbound listo desde hace más de 2 min.",
        True,
    ),
    (
        "health:main:calendar_unavailable",
        True,
        "critical",
        "🔴",
        "Calendar con tres errores seguidos.",
        True,
    ),
    ("billing", True, "notice", "🟡", "Mensajes facturables por encima del umbral mensual.", True),
    (
        "auth",
        True,
        "critical",
        "🔴",
        "Envío del canal principal rechazado por autenticación.",
        True,
    ),
]


def telegram_payload(text: str, at: datetime, rng: random.Random) -> dict[str, Any]:
    user_id = rng.randint(100_000_000, 999_999_999)
    return {
        "update_id": rng.randint(800_000_000, 899_999_999),
        "message": {
            "message_id": rng.randint(1, 10_000),
            "from": {"id": user_id, "is_bot": False, "first_name": "Cliente"},
            "chat": {"id": user_id, "type": "private"},
            "date": int(at.timestamp()),
            "text": text,
        },
    }


def whatsapp_payload(contact: Contact, text: str, at: datetime) -> dict[str, Any]:
    phone = (contact.phone_e164 or "").removeprefix("+")
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "dev",
                "changes": [
                    {
                        "value": {
                            "messaging_product": "whatsapp",
                            "contacts": [
                                {"profile": {"name": contact.display_name}, "wa_id": phone}
                            ],
                            "messages": [
                                {
                                    "from": phone,
                                    "id": f"wamid.dev{uuid7().hex}",
                                    "timestamp": str(int(at.timestamp())),
                                    "type": "text",
                                    "text": {"body": text},
                                }
                            ],
                        },
                        "field": "messages",
                    }
                ],
            }
        ],
    }


class Command(BaseCommand):
    help = "Crea actividad falsa y realista para desarrollar y evaluar el panel en local."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--days", type=int, default=None)
        parser.add_argument("--reset", action="store_true")

    def handle(self, *args: Any, **options: Any) -> None:
        if settings.ENVIRONMENT != "local":
            raise CommandError("Solo puede ejecutarse en local (ENVIRONMENT=local).")
        now = timezone.now()
        days = options["days"] or max(now.day, 1)
        tenants = [t for t in get_registry().tenants if t.document.status != "offboarded"]
        if not tenants:
            raise CommandError(
                "No hay negocios cargados: ejecute antes `seed_demos` o importe uno."
            )
        rng = random.Random()
        if options["reset"]:
            self._reset(tenants)
        for tenant in tenants:
            self._seed_tenant(tenant, now, days, rng)
        self._seed_alerts(tenants, now)
        self._seed_failed_job(tenants[0], now)
        self._seed_system_samples(now, rng)
        self._seed_state_files(now)
        self.stdout.write(self.style.SUCCESS(f"Actividad de desarrollo creada ({days} días)."))

    # ── reset: removes only what this command marks ──────────────────────

    def _reset(self, tenants: list[LoadedTenant]) -> None:
        for tenant in tenants:
            with tenant_tx(tenant.id):
                OutboundMessage.objects.filter(idem_key__startswith=CONTACT_MARKER).delete()
                InboundEvent.objects.filter(provider_event_id__startswith=CONTACT_MARKER).delete()
                Notification.objects.filter(idem_key__startswith=CONTACT_MARKER).delete()
                MetricEvent.objects.filter(idem_key__startswith=CONTACT_MARKER).delete()
                Contact.objects.filter(external_id__startswith=CONTACT_MARKER).delete()
        # fp_app has no DELETE on ops_alert (autobot/db/grants.py, ADR-009): bypass as fp_owner.
        OpsAlert.objects.using("owner").filter(kind__startswith=ALERT_MARKER).delete()
        with connections["default"].cursor() as cursor:
            cursor.execute("DELETE FROM procrastinate_jobs WHERE args->>%s = 'true'", [JOB_MARKER])

    # ── per-tenant conversation activity ──────────────────────────────────

    def _contacts(
        self, tenant: LoadedTenant, channel: str, now: datetime, rng: random.Random
    ) -> list[Contact]:
        contacts = []
        for i in range(rng.randint(4, 8)):
            contact, created = Contact.objects.get_or_create(
                tenant_id=tenant.id,
                channel=channel,
                external_id=f"{CONTACT_MARKER}{tenant.slug}-{i}",
                defaults={
                    "phone_e164": f"+34600{i:06d}",
                    "display_name": f"Cliente {i + 1}",
                    "last_activity_at": now,
                },
            )
            if created:
                contact.created_at = now - timedelta(days=30)
                contact.save(update_fields=["created_at"])
            contacts.append(contact)
        return contacts

    def _outbound_status(
        self, rng: random.Random, at: datetime
    ) -> tuple[str, datetime | None, str]:
        roll = rng.random()
        if roll < 0.08:
            return OutboundMessage.Status.UNKNOWN, at + timedelta(minutes=12), ""
        if roll < 0.15:
            return OutboundMessage.Status.FAILED, None, "HTTP 500"
        return OutboundMessage.Status.SENT, None, ""

    def _seed_tenant(
        self, tenant: LoadedTenant, now: datetime, days: int, rng: random.Random
    ) -> None:
        channel = Channel.DEMO_TG if tenant.is_demo else Channel.MAIN
        is_whatsapp = (
            not tenant.is_demo
            and tenant.document.channel is not None
            and tenant.document.channel.type == "whatsapp"
        )
        with tenant_tx(tenant.id):
            contacts = self._contacts(tenant, channel, now, rng)
            outbound_rows: list[OutboundMessage] = []
            notification_rows: list[Notification] = []
            metric_rows: list[MetricEvent] = []
            notifications_created = 0
            for day_offset in range(days):
                day = now - timedelta(days=day_offset)
                for _ in range(rng.randint(20, 60)):
                    contact = rng.choice(contacts)
                    at = day.replace(
                        hour=rng.randint(8, 21),
                        minute=rng.randint(0, 59),
                        second=rng.randint(0, 59),
                        microsecond=0,
                    )
                    text_in = rng.choice(
                        ["¿A qué hora abrís?", "Quiero una cita", "¿Cuánto cuesta?"]
                    )
                    payload = (
                        whatsapp_payload(contact, text_in, at)
                        if channel == Channel.DEMO_WA or is_whatsapp
                        else telegram_payload(text_in, at, rng)
                    )
                    inbound = InboundEvent.objects.create(
                        tenant_id=tenant.id,
                        channel=channel,
                        kind=InboundEvent.Kind.MESSAGE,
                        provider_event_id=f"{CONTACT_MARKER}{uuid7().hex}",
                        payload=payload,
                        status=InboundEvent.Status.DONE,
                        received_at=at,
                        processed_at=at,
                    )
                    status, unknown_at, last_error = self._outbound_status(rng, at)
                    billable = is_whatsapp and rng.random() < 0.7
                    message = OutboundMessage.objects.create(
                        tenant_id=tenant.id,
                        contact=contact,
                        channel=channel,
                        idem_key=f"{CONTACT_MARKER}{uuid7().hex}",
                        kind=OutboundMessage.Kind.REPLY,
                        payload=dump_outbound(Text("Gracias, le contestamos enseguida.")),
                        status=status,
                        billable=billable if is_whatsapp else None,
                        pricing_category=rng.choice(PRICING_CATEGORIES) if billable else None,
                        unknown_at=unknown_at,
                        last_error=last_error,
                        inbound_event=inbound,
                        sent_at=at if status == OutboundMessage.Status.SENT else None,
                    )
                    message.created_at = at
                    outbound_rows.append(message)
                    if tenant.document.pack == "bus":
                        metric = MetricEvent.objects.create(
                            tenant_id=tenant.id,
                            kind="schedule_query",
                            value=1,
                            idem_key=f"{CONTACT_MARKER}{uuid7().hex}",
                        )
                        metric.created_at = at
                        metric_rows.append(metric)
                if notifications_created < 3:
                    notice = Notification.objects.create(
                        tenant_id=tenant.id,
                        idem_key=f"{CONTACT_MARKER}{uuid7().hex}",
                        kind="booking_created",
                        text="Nueva cita confirmada.",
                        status=Notification.Status.SENT,
                        sent_at=day,
                    )
                    notice.created_at = day
                    notification_rows.append(notice)
                    notifications_created += 1
            if outbound_rows:
                OutboundMessage.objects.bulk_update(outbound_rows, ["created_at"])
            if notification_rows:
                Notification.objects.bulk_update(notification_rows, ["created_at"])
            if metric_rows:
                MetricEvent.objects.bulk_update(metric_rows, ["created_at"])

    # ── platform-wide activity ────────────────────────────────────────────

    def _seed_alerts(self, tenants: list[LoadedTenant], now: datetime) -> None:
        cycle = itertools.cycle(tenants)
        for index, (kind, tenant_specific, severity, emoji, message, resolved) in enumerate(
            ALERT_SAMPLES
        ):
            tenant = next(cycle) if tenant_specific else None
            text = f"{tenant.slug}: {emoji} {message}" if tenant else f"{emoji} {message}"
            OpsAlert.objects.create(
                kind=f"{ALERT_MARKER}{kind}",
                tenant_id=tenant.id if tenant else None,
                severity=severity,
                text=text,
                first_seen_at=now - timedelta(hours=index + 1),
                last_seen_at=now - timedelta(minutes=5 * (index + 1)),
                occurrences=index + 1,
                sent_count=1,
                last_delivery="sent",
                last_sent_at=now - timedelta(minutes=5 * (index + 1)),
                auto_resolves=True,
                resolved_at=now - timedelta(minutes=10 * (index + 1)) if resolved else None,
                resolved_by=("mariano" if index == 6 else "auto") if resolved else "",
            )

    def _seed_failed_job(self, tenant: LoadedTenant, now: datetime) -> None:
        args = json.dumps(
            {"tenant_id": str(tenant.id), "outbound_id": str(uuid7()), JOB_MARKER: True}
        )
        with connections["default"].cursor() as cursor:
            cursor.execute(
                "INSERT INTO procrastinate_jobs(task_name, queue_name, status, args, attempts)"
                " VALUES ('send_message', 'outbound', 'failed', %s, 3) RETURNING id",
                [args],
            )
            row = cursor.fetchone()
            assert row is not None
            (job_id,) = row
            base = now - timedelta(minutes=20)
            for offset, event_type in enumerate(("deferred", "started", "failed")):
                cursor.execute(
                    "INSERT INTO procrastinate_events(job_id, type, at) VALUES (%s, %s, %s)",
                    [job_id, event_type, base + timedelta(minutes=offset * 5)],
                )

    def _seed_system_samples(self, now: datetime, rng: random.Random) -> None:
        window_start = now - SAMPLE_WINDOW
        SystemSample.objects.filter(taken_at__gte=window_start).delete()
        samples = []
        taken = window_start
        db_bytes = 50_000_000
        while taken <= now:
            db_bytes += rng.randint(0, 500_000)
            samples.append(
                SystemSample(
                    taken_at=taken,
                    cpu_pct=round(rng.uniform(5, 60), 1),
                    mem_used_pct=round(rng.uniform(30, 80), 1),
                    load1=round(rng.uniform(0.1, 2.0), 2),
                    disk_used_pct=round(rng.uniform(40, 60), 1),
                    db_bytes=db_bytes,
                )
            )
            taken += SAMPLE_INTERVAL
        SystemSample.objects.bulk_create(samples)

    def _seed_state_files(self, now: datetime) -> None:
        state_dir = settings.OPS_STATE_DIR
        state_dir.mkdir(parents=True, exist_ok=True)
        backup = {
            "finished_at": (now - timedelta(hours=3)).isoformat(),
            "ok": True,
            "dump_bytes": 48_123_456,
        }
        tmp = state_dir / ".backup.json.tmp"
        tmp.write_text(json.dumps(backup))
        tmp.replace(state_dir / "backup.json")
        results = ["deployed", "already", "deployed", "rolled_back", "deployed"]
        lines = [
            json.dumps(
                {
                    "at": (now - timedelta(days=offset)).isoformat(),
                    "sha": "a" * 40,
                    "previous": "b" * 40,
                    "result": result,
                }
            )
            for offset, result in enumerate(results)
        ]
        (state_dir / "deploys.jsonl").write_text("\n".join(lines) + "\n")
        self._seed_containers(state_dir, now)

    def _seed_containers(self, state_dir: Path, now: datetime) -> None:
        release_sha = settings.RELEASE_SHA or "local"
        rows = []
        for service in EXPECTED_SERVICES:
            restart_count = 2 if service == "worker-outbound" else 0
            started_at = now - (
                timedelta(minutes=10) if service == "worker-outbound" else timedelta(days=1)
            )
            rows.append(
                {
                    "name": f"autobot-{service}-1",
                    "service": service,
                    "status": "running",
                    "health": "none" if service in ("db", "caddy") else "healthy",
                    "restart_count": restart_count,
                    "oom_killed": False,
                    "exit_code": 0,
                    "started_at": started_at.isoformat(),
                    "finished_at": None,
                    "image": f"ghcr.io/autobot/{service}:{release_sha}",
                }
            )
        doc = {
            "version": 1,
            "generated_at": now.isoformat(),
            "project": "autobot",
            "maintenance": None,
            "containers": rows,
        }
        tmp = state_dir / ".containers.json.tmp"
        tmp.write_text(json.dumps(doc))
        tmp.replace(state_dir / "containers.json")
