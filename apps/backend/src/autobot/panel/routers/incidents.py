"""Operational incident reads and explicitly authorised resolutions."""

from datetime import datetime
from typing import Any
from uuid import UUID

from django.db import transaction
from django.db.models import Case, IntegerField, OuterRef, Subquery, Value, When
from django.http import HttpRequest
from django.shortcuts import get_object_or_404
from ninja import Router, Schema
from procrastinate.contrib.django.models import ProcrastinateEvent, ProcrastinateJob

from autobot.ops import actions
from autobot.ops.audit import record
from autobot.ops.models import OpsAlert
from autobot.panel.errors import ApiError
from autobot.panel.routers.audit import page
from autobot.runtime.models import OutboundMessage
from autobot.runtime.notifications import resolve_alert
from autobot.tenancy.models import Tenant

router = Router(tags=["incidents"])


class AlertOut(Schema):
    id: UUID
    kind: str
    tenant_id: UUID | None
    tenant: str | None
    severity: str
    text: str
    first_seen_at: datetime
    last_seen_at: datetime
    occurrences: int
    sent_count: int
    last_sent_at: datetime | None
    last_delivery: str
    auto_resolves: bool
    resolved_at: datetime | None
    resolved_by: str | None


class OutboundIncidentOut(Schema):
    id: UUID
    tenant_id: UUID
    tenant: str
    channel: str
    status: str
    created_at: datetime
    last_error: str | None
    can_mark_sent: bool
    mark_sent_reason: str | None
    can_resend: bool
    resend_reason: str | None


class LastEventOut(Schema):
    type: str | None
    at: datetime | None


class JobOut(Schema):
    id: int
    at: datetime | None
    task_name: str
    queue: str
    status: str
    attempts: int
    ids: dict[str, str | int]
    last_event: LastEventOut
    can_retry: bool
    retry_reason: str | None


class IncidentsOut(Schema):
    alerts: list[AlertOut]
    outbound: list[OutboundIncidentOut]
    jobs: list[JobOut]


class AlertsPage(Schema):
    items: list[AlertOut]
    next_cursor: str | None


class JobsPage(Schema):
    items: list[JobOut]
    next_cursor: str | None


class MessageOut(Schema):
    message: str


def tenant_slugs() -> dict[UUID, str]:
    return dict(Tenant.objects.using("owner").values_list("id", "slug"))


def alert_row(a: OpsAlert, slugs: dict[UUID, str]) -> dict[str, Any]:
    return {
        "tenant": slugs.get(a.tenant_id) if a.tenant_id else None,
        **{
            name: getattr(a, name)
            for name in (
                "id",
                "kind",
                "tenant_id",
                "severity",
                "text",
                "first_seen_at",
                "last_seen_at",
                "occurrences",
                "sent_count",
                "last_sent_at",
                "last_delivery",
                "auto_resolves",
                "resolved_at",
                "resolved_by",
            )
        },
    }


def job_queryset() -> Any:
    latest = (
        ProcrastinateEvent.objects.using("owner")
        .filter(job_id=OuterRef("pk"))
        .order_by("-at", "-id")
    )
    return ProcrastinateJob.objects.using("owner").annotate(
        at=Subquery(latest.values("at")[:1]), event_type=Subquery(latest.values("type")[:1])
    )


def job_row(j: Any) -> dict[str, Any]:
    ok, reason = actions.can_retry(j)
    args = j.args if isinstance(j.args, dict) else {}
    ids = {
        k: v
        for k, v in args.items()
        if k.endswith("_id") and isinstance(v, (str, int)) and not isinstance(v, bool)
    }
    return dict(
        id=j.id,
        at=j.at,
        task_name=j.task_name,
        queue=j.queue_name,
        status=j.status,
        attempts=j.attempts,
        ids=ids,
        last_event={"type": j.event_type, "at": j.at},
        can_retry=ok,
        retry_reason=reason,
    )


@router.get("/incidents", response=IncidentsOut)
def incidents(request: HttpRequest) -> dict[str, Any]:
    alerts = (
        OpsAlert.objects.using("owner")
        .filter(resolved_at__isnull=True)
        .annotate(
            severity_rank=Case(
                When(severity="critical", then=Value(0)),
                When(severity="warning", then=Value(1)),
                default=Value(2),
                output_field=IntegerField(),
            )
        )
        .order_by("severity_rank", "-last_seen_at", "-id")
    )
    sends = []
    for m in (
        OutboundMessage.objects.using("owner")
        .filter(status__in=["unknown", "failed"])
        .select_related("tenant")
        .order_by("-created_at", "-id")
    ):
        mark, mark_reason = actions.can_mark_sent(m)
        resend, resend_reason = actions.can_resend(m, db_tenant=m.tenant)
        sends.append(
            dict(
                id=m.id,
                tenant_id=m.tenant_id,
                tenant=m.tenant.slug,
                channel=m.channel,
                status=m.status,
                created_at=m.created_at,
                last_error=m.last_error,
                can_mark_sent=mark,
                mark_sent_reason=mark_reason,
                can_resend=resend,
                resend_reason=resend_reason,
            )
        )
    slugs = tenant_slugs()
    return dict(
        alerts=[alert_row(a, slugs) for a in alerts],
        outbound=sends,
        jobs=[job_row(j) for j in job_queryset().filter(status="failed").order_by("-at", "-id")],
    )


class Confirmation(Schema):
    confirm_duplicate_risk: Any = False


def result(value: actions.Result) -> dict[str, str]:
    if not value.ok:
        raise ApiError("conflict", value.message, 409)
    return {"message": value.message}


@router.post("/outbound/{id}/mark-sent", response=MessageOut)
def mark_sent(request: HttpRequest, id: UUID) -> dict[str, str]:
    get_object_or_404(OutboundMessage.objects.using("owner"), pk=id)
    return result(actions.mark_sent(id, actor=request.user.username))


@router.post("/outbound/{id}/resend", response=MessageOut)
def resend(request: HttpRequest, id: UUID, payload: Confirmation | None = None) -> dict[str, str]:
    if payload is None or payload.confirm_duplicate_risk is not True:
        raise ApiError("bad_request", "Confirme el riesgo de duplicado.", 400)
    get_object_or_404(OutboundMessage.objects.using("owner"), pk=id)
    return result(actions.resend(id, actor=request.user.username))


@router.post("/jobs/{id}/retry", response=MessageOut)
def retry(request: HttpRequest, id: int) -> dict[str, str]:
    get_object_or_404(ProcrastinateJob.objects.using("owner"), pk=id)
    return result(actions.retry_job(id, actor=request.user.username))


@router.post("/alerts/{id}/resolve", response=MessageOut)
def resolve(request: HttpRequest, id: UUID) -> dict[str, str]:
    with transaction.atomic(using="owner"):
        alert = get_object_or_404(OpsAlert.objects.using("owner").select_for_update(), pk=id)
        if alert.auto_resolves:
            raise ApiError("bad_request", "Esta alerta se resuelve automáticamente.", 400)
        if alert.resolved_at:
            raise ApiError("conflict", "La alerta ya está resuelta.", 409)
        resolve_alert(alert, by=request.user.username)
        record(
            actor=request.user.username,
            action="alert.resolve",
            summary="Operador resuelve alerta.",
            tenant_id=alert.tenant_id,
            target_type="ops_alert",
            target_id=str(id),
        )
    return {"message": "Alerta resuelta."}


@router.get("/alerts", response=AlertsPage)
def alerts(
    request: HttpRequest, state: str = "", cursor: str = "", limit: int = 50
) -> dict[str, Any]:
    qs = OpsAlert.objects.using("owner").all()
    if state:
        if state not in ("open", "resolved"):
            raise ApiError("bad_request", "Estado no válido.", 400)
        qs = qs.filter(resolved_at__isnull=state == "open")
    rows, next_cursor = page(qs, field="last_seen_at", cursor=cursor, limit=limit)
    slugs = tenant_slugs()
    return {"items": [alert_row(a, slugs) for a in rows], "next_cursor": next_cursor}


@router.get("/jobs", response=JobsPage)
def jobs(
    request: HttpRequest, status: str = "", queue: str = "", cursor: str = "", limit: int = 50
) -> dict[str, Any]:
    qs = job_queryset()
    if status:
        qs = qs.filter(status=status)
    if queue:
        qs = qs.filter(queue_name=queue)
    rows, next_cursor = page(qs, field="at", cursor=cursor, limit=limit, numeric=True)
    return {"items": [job_row(j) for j in rows], "next_cursor": next_cursor}
