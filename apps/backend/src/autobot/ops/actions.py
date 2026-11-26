"""Operator actions on ambiguous sends and failed jobs. Used by the
panel and by the `outbound_resolve`/`job_retry` commands; previously inline in admin.py."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from django.db import transaction
from django.utils import timezone
from procrastinate import App
from procrastinate.contrib.django.models import ProcrastinateJob

from autobot.channels.demo.doors import door
from autobot.ops import audit, cases, incidents
from autobot.runtime.jobs import OUTBOUND, SEND_MESSAGE, app
from autobot.runtime.models import DEMO_CHANNELS, Channel, OutboundMessage
from autobot.runtime.outbound import (
    MAX_AMBIGUOUS_RESENDS,
    PROACTIVE_TTL,
    RECONCILE_WAIT,
    REPLY_TTL,
    message_lock,
    send_priority,
)
from autobot.runtime.queue import enqueue
from autobot.runtime.queue import queue_app as _queue_app
from autobot.tenancy.models import Tenant
from autobot.tenancy.registry import tenant_by_id

OWNER = "owner"
# Delivery failures need deliberate resolution, never a blind retry.
NOT_RETRYABLE_TASKS = ("send_message", "send_notification")


@dataclass(frozen=True)
class Result:
    ok: bool
    message: str


def queue_app() -> App:
    """The app that queues through the `owner` connection (the panel's)."""
    return _queue_app(OWNER)


def can_mark_sent(message: OutboundMessage) -> tuple[bool, str]:
    if message.status != "unknown":
        return False, "No es un envío ambiguo."
    if message.unknown_at is None or message.unknown_at >= timezone.now() - RECONCILE_WAIT:
        return False, "Un envío ambiguo reciente puede resolverse solo; espere 10 minutos."
    return True, ""


def effective_not_after(message: OutboundMessage) -> datetime | None:
    """The pack's deadline for a proactive message. Rows from before `not_after` was stored
    infer it: an `expires_at` shorter than the 24 h window can only come from `not_after`."""
    if message.kind != "proactive":
        return None
    if message.not_after is not None:
        return message.not_after
    if (
        message.expires_at is not None
        and message.expires_at < message.created_at + PROACTIVE_TTL - timedelta(minutes=1)
    ):
        return message.expires_at
    return None


def _past_not_after(message: OutboundMessage) -> bool:
    limit = effective_not_after(message)
    return limit is not None and limit <= timezone.now()


def can_discard(message: OutboundMessage) -> tuple[bool, str]:
    """Any ambiguous send, with no waiting time: the person decided (ADR-031)."""
    if message.status != "unknown":
        return False, "No es un envío ambiguo."
    return True, ""


def can_resend(message: OutboundMessage, *, db_tenant: Tenant) -> tuple[bool, str]:
    ok, reason = can_mark_sent(message)
    if not ok:
        return ok, reason
    return _deliverable(message, db_tenant=db_tenant)


def _deliverable(message: OutboundMessage, *, db_tenant: Tenant) -> tuple[bool, str]:
    if _past_not_after(message):
        return False, "El mensaje ya no es útil: pasó su fecha límite (p. ej. la cita)."
    if message.payload is None:
        return False, "El contenido del mensaje ya no está disponible."
    # Inside the caller's transaction (row lock held): a miss here never waits nor
    # rebuilds, it only asks the refresher and answers from the newest snapshot.
    tenant = tenant_by_id(message.tenant_id)
    if tenant is None or tenant.ambiguous:
        return False, "El negocio no se puede resolver de forma inequívoca."
    if tenant.document.status == "offboarded" or db_tenant.status == "offboarded":
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
    incidents.settle_ambiguous(message.tenant_id, using=OWNER)
    return Result(True, "Marcado como enviado.")


def discard(outbound_id: UUID, *, actor: str) -> Result:
    """Final state `discarded`: it is not resent, the reconciliation ignores it and it does
    not come back (a later provider status that proves delivery still makes it `sent`)."""
    with transaction.atomic(using=OWNER):
        message = OutboundMessage.objects.using(OWNER).select_for_update().get(pk=outbound_id)
        ok, reason = can_discard(message)
        if not ok:
            return Result(False, reason)
        message.status = "discarded"
        message.unknown_at = None
        message.save(using=OWNER, update_fields=["status", "unknown_at"])
        audit.record(
            actor=actor,
            action="outbound.discard",
            summary="Operador descarta un envío ambiguo.",
            tenant_id=message.tenant_id,
            target_type="outbound_message",
            target_id=str(message.pk),
        )
    incidents.settle_ambiguous(message.tenant_id, using=OWNER)
    return Result(True, "Envío descartado.")


def discard_all(tenant_id: UUID, *, actor: str) -> Result:
    """«Descartar todos» (ADR-031): every undecided ambiguous send of a tenant (the cases
    of its `outbound_ambiguous`) becomes `discarded`. Sends nothing, unlike the retired
    bulk resend. One audit record with the count; the incident closes."""
    now = timezone.now()
    with transaction.atomic(using=OWNER):
        undecided = cases.ambiguous(
            OutboundMessage.objects.using(OWNER).filter(tenant_id=tenant_id), now
        )
        ids = list(undecided.select_for_update().values_list("id", flat=True))
        count = (
            OutboundMessage.objects.using(OWNER)
            .filter(id__in=ids, status="unknown")
            .update(status="discarded", unknown_at=None)
        )
        if count:
            audit.record(
                actor=actor,
                action="outbound.discard_all",
                summary="Operador descarta todos los envíos ambiguos de un negocio.",
                tenant_id=tenant_id,
                target_type="tenant",
                target_id=str(tenant_id),
                details={"count": count},
            )
    incidents.settle_ambiguous(tenant_id, using=OWNER)
    if not count:
        return Result(True, "No quedaba ningún envío sin confirmar.")
    return Result(True, f"{count} envíos descartados.")


def _requeue(message: OutboundMessage) -> None:
    """A person decided to resend it: it gets a fresh time limit (or it would expire at
    once) and the platform never adds its own resend on top (`ambiguous_resends`)."""
    message.status = "pending"
    message.unknown_at = None
    now = timezone.now()
    message.expires_at = now + (PROACTIVE_TTL if message.kind == "proactive" else REPLY_TTL)
    limit = effective_not_after(message)
    if limit is not None:
        if limit <= now:
            raise ValueError("not_after has passed")  # callers check `_deliverable` first
        message.expires_at = min(message.expires_at, limit)
    message.ambiguous_resends = max(message.ambiguous_resends, MAX_AMBIGUOUS_RESENDS)
    message.save(
        using=OWNER, update_fields=["status", "unknown_at", "expires_at", "ambiguous_resends"]
    )
    # Inside the transaction, through the same `owner` connection that saved the message:
    # the job exists only if the status change commits (and is not visible to the worker
    # before it does).
    enqueue(
        SEND_MESSAGE,
        {"tenant_id": str(message.tenant_id), "outbound_id": str(message.pk)},
        queue=OUTBOUND,
        lock=message_lock(message.tenant_id, message),
        priority=send_priority(message.kind),
        alias=OWNER,
    )


def resend(outbound_id: UUID, *, actor: str) -> Result:
    with transaction.atomic(using=OWNER):
        message = OutboundMessage.objects.using(OWNER).select_for_update().get(pk=outbound_id)
        db_tenant = Tenant.objects.using(OWNER).select_for_update().get(pk=message.tenant_id)
        ok, reason = can_resend(message, db_tenant=db_tenant)
        if not ok:
            return Result(False, reason)
        _requeue(message)
        audit.record(
            actor=actor,
            action="outbound.resend",
            summary="Operador autoriza reenvío con riesgo de duplicado.",
            tenant_id=message.tenant_id,
            target_type="outbound_message",
            target_id=str(message.pk),
        )
    incidents.settle_ambiguous(message.tenant_id, using=OWNER)
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
    incidents.settle_failed_job(job.task_name, using=OWNER)
    return Result(True, "Trabajo reencolado.")
