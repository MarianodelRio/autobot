"""Operator actions on ambiguous sends and failed jobs (DESIGN §6.4, §9.7). Used by the
panel and by the `outbound_resolve`/`job_retry` commands; previously inline in admin.py."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import Any
from uuid import UUID

from django.db import transaction
from django.utils import timezone
from procrastinate import App
from procrastinate.contrib.django.django_connector import DjangoConnector
from procrastinate.contrib.django.models import ProcrastinateJob

from autobot.channels.demo.doors import door
from autobot.ops import audit
from autobot.runtime.locks import contact_hash
from autobot.runtime.models import DEMO_CHANNELS, Channel, OutboundMessage
from autobot.tenancy.models import Tenant
from autobot.tenancy.registry import get_registry

OWNER = "owner"
# Delivery failures need deliberate resolution, never a blind retry.
NOT_RETRYABLE_TASKS = ("send_message", "send_notification")


@dataclass(frozen=True)
class Result:
    ok: bool
    message: str


def queue_app() -> App:
    return App(connector=DjangoConnector(alias=OWNER))


def _deferrer(task: Any, *, tenant_id: Any, outbound_id: Any) -> Callable[[], None]:
    """A closure over `task.defer`'s ids, for `transaction.on_commit`: calling
    `task.defer` directly there would re-evaluate `tenant_id`/`outbound_id` against
    whatever the loop variable holds by the time it runs, not the row being resolved."""
    return lambda: task.defer(tenant_id=str(tenant_id), outbound_id=str(outbound_id))


def can_mark_sent(message: OutboundMessage) -> tuple[bool, str]:
    if message.status != "unknown":
        return False, "No es un envío ambiguo."
    if message.unknown_at is None or message.unknown_at >= timezone.now() - timedelta(minutes=10):
        return False, "Un envío ambiguo reciente puede resolverse solo; espere 10 minutos."
    return True, ""


def can_resend(message: OutboundMessage, *, db_tenant: Tenant) -> tuple[bool, str]:
    ok, reason = can_mark_sent(message)
    if not ok:
        return ok, reason
    if message.payload is None:
        return False, "El contenido del mensaje ya no está disponible."
    tenant = get_registry().by_id.get(message.tenant_id)
    if tenant is None or tenant.ambiguous:
        return False, "El negocio no se puede resolver de forma inequívoca."
    if tenant.file.status == "offboarded" or db_tenant.status == "offboarded":
        return False, "El negocio está dado de baja."
    if message.channel == "main":
        if not tenant.main_enabled:
            return False, "El canal principal del negocio está desactivado."
    elif message.channel in DEMO_CHANNELS:
        if door(Channel(message.channel)) is None:
            return False, "La puerta de demo de ese canal no está configurada."
    else:
        return False, "Canal desconocido."
    return True, ""


def can_retry(job: ProcrastinateJob) -> tuple[bool, str]:
    if job.status != "failed":
        return False, "El trabajo no está en estado fallido."
    if job.task_name in NOT_RETRYABLE_TASKS:
        return False, "Revise el resultado del envío antes de actuar."
    from autobot.jobs import app

    if job.task_name not in app.tasks:
        return False, "La tarea ya no existe."
    return True, ""


def mark_sent(outbound_id: UUID, *, actor: str) -> Result:
    with transaction.atomic(using=OWNER):
        message = OutboundMessage.objects.using(OWNER).select_for_update().get(pk=outbound_id)
        ok, reason = can_mark_sent(message)
        if not ok:
            return Result(False, reason)
        message.status = "sent"
        message.unknown_at = None
        message.sent_at = message.sent_at or timezone.now()
        message.save(using=OWNER, update_fields=["status", "unknown_at", "sent_at"])
        audit.record(
            actor=actor,
            action="outbound.mark_sent",
            summary="Operador confirma enviado.",
            tenant_id=message.tenant_id,
            target_type="outbound_message",
            target_id=str(message.pk),
        )
    return Result(True, "Marcado como enviado.")


def resend(outbound_id: UUID, *, actor: str) -> Result:
    with transaction.atomic(using=OWNER):
        message = OutboundMessage.objects.using(OWNER).select_for_update().get(pk=outbound_id)
        db_tenant = Tenant.objects.using(OWNER).select_for_update().get(pk=message.tenant_id)
        ok, reason = can_resend(message, db_tenant=db_tenant)
        if not ok:
            return Result(False, reason)
        message.status = "pending"
        message.unknown_at = None
        message.save(using=OWNER, update_fields=["status", "unknown_at"])
        contact = message.contact
        lock = contact_hash(message.tenant_id, contact.channel, contact.external_id)
        task = queue_app().configure_task(name="send_message", queue="outbound", lock=f"out:{lock}")
        # After commit: the worker runs on its own connection, so a job deferred here
        # could start before this row's own save is visible to it.
        transaction.on_commit(_deferrer(task, tenant_id=message.tenant_id, outbound_id=message.pk))
        audit.record(
            actor=actor,
            action="outbound.resend",
            summary="Operador autoriza reenvío con riesgo de duplicado.",
            tenant_id=message.tenant_id,
            target_type="outbound_message",
            target_id=str(message.pk),
        )
    return Result(True, "Reenvío autorizado.")


def retry_job(job_id: int, *, actor: str) -> Result:
    with transaction.atomic(using=OWNER):
        job = ProcrastinateJob.objects.using(OWNER).select_for_update().get(pk=job_id)
        ok, reason = can_retry(job)
        if not ok:
            return Result(False, reason)
        raw_tenant_id = job.args.get("tenant_id") if isinstance(job.args, dict) else None
        tenant_id = UUID(raw_tenant_id) if raw_tenant_id else None
        queue_app().job_manager.retry_job_by_id(job.pk, timezone.now())
        audit.record(
            actor=actor,
            action="job.retry",
            summary="Operador reintenta trabajo fallido idempotente.",
            tenant_id=tenant_id,
            target_type="job",
            target_id=str(job.pk),
        )
    return Result(True, "Trabajo reencolado.")
