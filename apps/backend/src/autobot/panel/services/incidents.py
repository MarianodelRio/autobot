"""The Incidencias screen (ADR-031): the open incidents of `ops.incidents.open_incidents`
with a preview of their cases, the cases of one incident page by page, and the closed
ones. Panel service code: every query crosses tenants, so it runs `.using("owner")` and
filters by the incident's tenant itself."""

from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from django.db.models import Max, OuterRef, QuerySet, Subquery
from django.utils import timezone
from ninja import Schema
from procrastinate.contrib.django.models import ProcrastinateEvent, ProcrastinateJob
from pydantic import Field

from autobot.ops import actions, cases, incidents
from autobot.ops.incidents import Closed, Incident, Nature, Severity
from autobot.ops.models import OpsAlert
from autobot.ops.runbooks import runbook_url
from autobot.ops.send_errors import describe
from autobot.panel.services.pagination import page
from autobot.runtime.models import Notification, OutboundMessage
from autobot.tenancy.models import Tenant
from autobot.tenancy.registry import tenant_by_id

OWNER = "owner"
PREVIEW = 20


class SendCase(Schema):
    type: Literal["send"] = "send"
    id: UUID
    channel: str
    status: str
    created_at: datetime
    error_class: str | None
    error_title: str | None
    error_advice: str | None
    can_mark_sent: bool
    mark_sent_reason: str | None
    can_resend: bool
    resend_reason: str | None
    can_discard: bool
    discard_reason: str | None


class JobCase(Schema):
    type: Literal["job"] = "job"
    id: int
    task: str
    task_label: str
    failed_at: datetime | None
    can_retry: bool
    retry_reason: str | None


class NoticeCase(Schema):
    type: Literal["notice"] = "notice"
    id: UUID
    status: str
    created_at: datetime


type CaseOut = Annotated[SendCase | JobCase | NoticeCase, Field(discriminator="type")]


class IncidentOut(Schema):
    id: UUID
    kind: str
    nature: Nature
    severity: Severity
    tenant_id: UUID | None
    tenant: str | None
    title: str
    advice: str
    # The text ops_check wrote (also what Telegram got): the figures of this pass.
    text: str
    # `/docs/...` page that explains what to do; None when the kind has none.
    runbook: str | None
    first_seen_at: datetime
    last_seen_at: datetime
    case_count: int
    last_case_at: datetime | None
    # A reopened event: how many cases came after the last review («N nuevos»).
    new_since_review: int | None
    reviewable: bool
    # sent | failed | unconfigured | panel (🟡, never pushed) | throttled | "" | cooldown
    delivery: str
    # Up to PREVIEW cases, newest first; the rest through `GET incidents/{id}/cases`.
    cases: list[CaseOut]


class SeverityCounts(Schema):
    critical: int
    warning: int
    notice: int


class IncidentsOut(Schema):
    items: list[IncidentOut]
    total: int  # 0 is «Todo en orden»
    by_severity: SeverityCounts


class CasesPage(Schema):
    items: list[CaseOut]
    next_cursor: str | None


class ClosedIncidentOut(Schema):
    id: UUID
    kind: str
    nature: Nature
    severity: Severity
    tenant: str | None
    title: str
    text: str
    runbook: str | None
    first_seen_at: datetime
    last_seen_at: datetime
    resolved_at: datetime
    case_count: int
    # auto (the cause went away) | outage (explained by a provider outage) | review (a
    # person reviewed it) | info (a one-off notice, born closed)
    closed: Closed
    closed_by: str | None  # the reviewer, for `review`


class ClosedPage(Schema):
    items: list[ClosedIncidentOut]
    next_cursor: str | None


def tenant_slugs() -> dict[UUID, str]:
    return dict(Tenant.objects.using(OWNER).values_list("id", "slug"))


# ── Cases ───────────────────────────────────────────────────────────────────


def _sends(alert: OpsAlert) -> QuerySet[OutboundMessage] | None:
    if alert.tenant_id is None:
        return None
    base = OutboundMessage.objects.using(OWNER).filter(tenant_id=alert.tenant_id)
    if alert.kind == "outbound_ambiguous":
        return cases.ambiguous(base, timezone.now())
    if alert.kind.startswith("outbound_rejected:"):
        cls = alert.kind.removeprefix("outbound_rejected:")
        after = alert.review_watermark or alert.first_seen_at - incidents.BOOTSTRAP
        pairs = cases.rejected_pairs(base, tenant_by_id(alert.tenant_id), after).get(cls, [])
        return cases.rejected(base, pairs, after)
    return None


def _notices(alert: OpsAlert) -> QuerySet[Notification] | None:
    if alert.tenant_id is None:
        return None
    base = Notification.objects.using(OWNER).filter(tenant_id=alert.tenant_id)
    if alert.kind == "owner_unlinked":
        return cases.held_notices(base, timezone.now())
    if alert.kind == "notification_failed":
        after = alert.review_watermark or alert.first_seen_at - incidents.BOOTSTRAP
        return cases.lost_notices(base, after)
    return None


def _jobs(alert: OpsAlert) -> QuerySet[ProcrastinateJob] | None:
    if not alert.kind.startswith("failed_job:"):
        return None
    task = alert.kind.removeprefix("failed_job:")
    after = alert.review_watermark or alert.first_seen_at - incidents.BOOTSTRAP
    failed_at = (
        ProcrastinateEvent.objects.using(OWNER)
        .filter(job_id=OuterRef("pk"), type="failed")
        .values("job_id")
        .annotate(at=Max("at"))
        .values("at")[:1]
    )
    jobs: QuerySet[ProcrastinateJob] = (
        ProcrastinateJob.objects.using(OWNER)
        .filter(status="failed", task_name=task)
        .annotate(failed_at=Subquery(failed_at))
        .filter(failed_at__gt=after)
    )
    return jobs


def _send_case(message: OutboundMessage, db_tenant: Tenant | None) -> SendCase:
    error = None
    if message.status == OutboundMessage.Status.FAILED and message.last_error:
        tenant = tenant_by_id(message.tenant_id)
        error = describe(
            cases.message_class(tenant, message.channel, message.last_error), message.last_error
        )
    mark, mark_reason = actions.can_mark_sent(message)
    if db_tenant is None:
        resend, resend_reason = False, "El negocio ya no existe."
    else:
        resend, resend_reason = actions.can_resend(message, db_tenant=db_tenant)
    discard, discard_reason = actions.can_discard(message)
    return SendCase(
        id=message.id,
        channel=message.channel,
        status=message.status,
        created_at=message.created_at,
        error_class=error.cls if error else None,
        error_title=error.title if error else None,
        error_advice=error.advice if error else None,
        can_mark_sent=mark,
        mark_sent_reason=mark_reason or None,
        can_resend=resend,
        resend_reason=resend_reason or None,
        can_discard=discard,
        discard_reason=discard_reason or None,
    )


def _job_case(job: Any) -> JobCase:
    ok, reason = actions.can_retry(job)
    return JobCase(
        id=job.id,
        task=job.task_name,
        task_label=incidents.task_label(job.task_name),
        failed_at=job.failed_at,
        can_retry=ok,
        retry_reason=reason or None,
    )


def case_page(alert: OpsAlert, *, cursor: str = "", limit: int = PREVIEW) -> CasesPage:
    """The cases of an incident, newest first, `limit` at a time."""
    sends = _sends(alert)
    if sends is not None:
        db_tenant = Tenant.objects.using(OWNER).filter(pk=alert.tenant_id or "").first()
        rows, next_cursor = page(sends, field="created_at", cursor=cursor, limit=limit)
        return CasesPage(items=[_send_case(m, db_tenant) for m in rows], next_cursor=next_cursor)
    notices = _notices(alert)
    if notices is not None:
        rows, next_cursor = page(notices, field="created_at", cursor=cursor, limit=limit)
        return CasesPage(
            items=[NoticeCase(id=n.id, status=n.status, created_at=n.created_at) for n in rows],
            next_cursor=next_cursor,
        )
    jobs = _jobs(alert)
    if jobs is not None:
        rows, next_cursor = page(jobs, field="failed_at", cursor=cursor, limit=limit, numeric=True)
        return CasesPage(items=[_job_case(j) for j in rows], next_cursor=next_cursor)
    return CasesPage(items=[], next_cursor=None)


# ── Open and closed incidents ───────────────────────────────────────────────


def _incident(incident: Incident, slugs: dict[UUID, str]) -> IncidentOut:
    row = incident.row
    return IncidentOut(
        id=row.id,
        kind=row.kind,
        nature=incident.info.nature,
        severity=incidents.as_severity(row.severity),
        tenant_id=row.tenant_id,
        tenant=slugs.get(row.tenant_id) if row.tenant_id else None,
        title=incident.info.title,
        advice=incident.info.advice,
        text=row.text,
        runbook=runbook_url(row.kind),
        first_seen_at=row.first_seen_at,
        last_seen_at=row.last_seen_at,
        case_count=row.case_count,
        last_case_at=row.last_case_at,
        new_since_review=incident.new_since_review,
        reviewable=incident.info.nature == "event",
        delivery=row.last_delivery,
        cases=case_page(row).items if incident.info.cases else [],
    )


def open_list() -> IncidentsOut:
    found = incidents.open_incidents(using=OWNER)
    slugs = tenant_slugs()
    by_severity = incidents.counts(i.severity for i in found)
    return IncidentsOut(
        items=[_incident(i, slugs) for i in found],
        total=len(found),
        by_severity=SeverityCounts(**by_severity),
    )


def closed_page(*, cursor: str = "", limit: int = 50) -> ClosedPage:
    qs = OpsAlert.objects.using(OWNER).filter(resolved_at__isnull=False)
    rows, next_cursor = page(qs, field="resolved_at", cursor=cursor, limit=limit)
    slugs = tenant_slugs()
    items = []
    for row in rows:
        info = incidents.kind_info(row.kind)
        how = incidents.closed_how(row)
        items.append(
            ClosedIncidentOut(
                id=row.id,
                kind=row.kind,
                nature=info.nature,
                severity=incidents.as_severity(row.severity),
                tenant=slugs.get(row.tenant_id) if row.tenant_id else None,
                title=info.title,
                text=row.text,
                runbook=runbook_url(row.kind),
                first_seen_at=row.first_seen_at,
                last_seen_at=row.last_seen_at,
                resolved_at=row.resolved_at,
                case_count=row.case_count,
                closed=how,
                closed_by=row.resolved_by if how == "review" else None,
            )
        )
    return ClosedPage(items=items, next_cursor=next_cursor)
