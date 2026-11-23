"""Operational incident reads and explicitly authorised resolutions."""

from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from django.db import transaction
from django.db.models import Case, Count, IntegerField, OuterRef, Subquery, Value, When
from django.http import HttpRequest
from django.shortcuts import get_object_or_404
from ninja import Query, Router, Schema
from procrastinate.contrib.django.models import ProcrastinateEvent, ProcrastinateJob
from pydantic import Field

from autobot.ops import actions
from autobot.ops.audit import record
from autobot.ops.models import OpsAlert
from autobot.ops.runbooks import runbook_url
from autobot.panel.errors import ApiError
from autobot.panel.services.pagination import page
from autobot.panel.stepup import require_recent_reauth
from autobot.runtime.models import Notification, OutboundMessage
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
    # `/docs/...` page that explains what to do; None when the alert has no runbook.
    runbook: str | None


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


class HeldNoticesOut(Schema):
    tenant_id: UUID
    tenant: str
    count: int


class IncidentsOut(Schema):
    alerts: list[AlertOut]
    outbound: list[OutboundIncidentOut]
    jobs: list[JobOut]
    # Each list is capped at `limit`; the totals say how many there really are, so the
    # screen can tell "showing 100 of 4,000" instead of silently hiding the rest.
    alerts_total: int
    outbound_total: int
    jobs_total: int
    # Owner notices kept because the owner has no chat linked, per business.
    held_notices: list[HeldNoticesOut]


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
        "runbook": runbook_url(a.kind),
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
def incidents(
    request: HttpRequest, limit: Annotated[int, Query(ge=1, le=200)] = 100
) -> dict[str, Any]:
    open_alerts = OpsAlert.objects.using("owner").filter(resolved_at__isnull=True)
    failed_sends = OutboundMessage.objects.using("owner").filter(status__in=["unknown", "failed"])
    failed_jobs = ProcrastinateJob.objects.using("owner").filter(status="failed")
    alerts = open_alerts.annotate(
        severity_rank=Case(
            When(severity="critical", then=Value(0)),
            When(severity="warning", then=Value(1)),
            default=Value(2),
            output_field=IntegerField(),
        )
    ).order_by("severity_rank", "-last_seen_at", "-id")[:limit]
    sends = []
    for m in failed_sends.select_related("tenant").order_by("-created_at", "-id")[:limit]:
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
    held = (
        Notification.objects.using("owner")
        .filter(status=Notification.Status.HELD)
        .values("tenant_id")
        .annotate(count=Count("id"))
        .order_by("-count")[:50]
    )
    return dict(
        held_notices=[
            dict(tenant_id=h["tenant_id"], tenant=slugs.get(h["tenant_id"], "—"), count=h["count"])
            for h in held
        ],
        alerts=[alert_row(a, slugs) for a in alerts],
        outbound=sends,
        jobs=[
            job_row(j)
            for j in job_queryset().filter(status="failed").order_by("-at", "-id")[:limit]
        ],
        alerts_total=open_alerts.count(),
        outbound_total=failed_sends.count(),
        jobs_total=failed_jobs.count(),
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


class BulkFilter(Schema):
    tenant_id: UUID | None = None
    statuses: list[str] = list(actions.BULK_STATUSES)
    since: datetime | None = None
    until: datetime | None = None


class BulkPreviewOut(Schema):
    total: int
    will_resend: int
    cap: int


class BulkResendIn(BulkFilter):
    # Explicit selection; when given, the filters are ignored.
    ids: list[UUID] | None = Field(default=None, max_length=actions.BULK_CAP)
    confirm_duplicate_risk: Any = False


class BulkResendOut(Schema):
    message: str
    selected: int
    resent: int
    skipped: int
    over_cap: int


def _bulk_queryset(f: BulkFilter) -> Any:
    bad = [x for x in f.statuses if x not in actions.BULK_STATUSES]
    if bad or not f.statuses:
        raise ApiError("bad_request", "Estado no válido para reenviar.", 400)
    for bound in (f.since, f.until):
        if bound is not None and bound.utcoffset() is None:
            raise ApiError("bad_request", "Las fechas deben incluir zona horaria.", 400)
    if f.since is not None and f.until is not None and f.since >= f.until:
        raise ApiError("bad_request", "«Desde» debe ser anterior a «hasta».", 400)
    return actions.bulk_queryset(
        tenant_id=f.tenant_id, statuses=f.statuses, since=f.since, until=f.until
    )


@router.post("/outbound/resend-bulk/preview", response=BulkPreviewOut)
def resend_bulk_preview(request: HttpRequest, payload: BulkFilter) -> dict[str, int]:
    total = _bulk_queryset(payload).count()
    return {"total": total, "will_resend": min(total, actions.BULK_CAP), "cap": actions.BULK_CAP}


@router.post("/outbound/resend-bulk", response=BulkResendOut)
@require_recent_reauth()
def resend_bulk(request: HttpRequest, payload: BulkResendIn) -> dict[str, Any]:
    """Resend after an incident: the selected messages or those matching a filter, at most
    `BULK_CAP` per action (oldest first; run it again for the rest). Needs a recent TOTP."""
    if payload.confirm_duplicate_risk is not True:
        raise ApiError("bad_request", "Confirme el riesgo de duplicado.", 400)
    if payload.ids is not None:
        ids = list(dict.fromkeys(payload.ids))
        if len(ids) > actions.BULK_CAP:
            raise ApiError("bad_request", f"Máximo {actions.BULK_CAP} mensajes por acción.", 400)
        over_cap = 0
    else:
        qs = _bulk_queryset(payload)
        total = qs.count()
        ids = list(qs.order_by("created_at", "id").values_list("id", flat=True)[: actions.BULK_CAP])
        over_cap = max(total - len(ids), 0)
    if not ids:
        raise ApiError("bad_request", "Ningún mensaje coincide.", 400)
    result = actions.resend_many(ids, over_cap=over_cap, actor=request.user.username)
    return {
        "message": f"{result.resent} mensajes reenviados, {result.skipped} omitidos.",
        "selected": result.selected,
        "resent": result.resent,
        "skipped": result.skipped,
        "over_cap": result.over_cap,
    }


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
