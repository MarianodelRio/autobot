"""The incidents (ADR-031): the open ones with their cases, their review, the actions
on their cases and the closed ones."""

from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from django.http import HttpRequest
from django.shortcuts import get_object_or_404
from ninja import Query, Router, Schema
from procrastinate.contrib.django.models import ProcrastinateJob

from autobot.ops import actions
from autobot.ops import incidents as incident_kinds
from autobot.ops.models import OpsAlert
from autobot.panel.errors import ApiError
from autobot.panel.services import incidents
from autobot.runtime.models import OutboundMessage

router = Router(tags=["incidents"])


class MessageOut(Schema):
    message: str


@router.get("/incidents", response=incidents.IncidentsOut)
def open_incidents(request: HttpRequest) -> incidents.IncidentsOut:
    """Every open incident, most severe and most recent first, with up to 20 cases each."""
    return incidents.open_list()


@router.get("/incidents/history", response=incidents.ClosedPage)
def closed_incidents(
    request: HttpRequest,
    cursor: str = "",
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> incidents.ClosedPage:
    """The closed incidents, most recently closed first, and how each one closed."""
    return incidents.closed_page(cursor=cursor, limit=limit)


@router.get("/incidents/{id}/cases", response=incidents.CasesPage)
def incident_cases(
    request: HttpRequest,
    id: UUID,
    cursor: str = "",
    limit: Annotated[int, Query(ge=1, le=100)] = incidents.PREVIEW,
) -> incidents.CasesPage:
    """The cases of an incident, newest first. `cursor`: the incident's
    `cases_next_cursor` (continues after its preview) or a page's `next_cursor`."""
    alert = get_object_or_404(OpsAlert.objects.using("owner"), pk=id)
    return incidents.case_page(alert, cursor=cursor, limit=limit)


class ReviewIn(Schema):
    # The newest case time the panel showed (`last_case_at`): the review never covers a
    # case the person did not see.
    last_case_at: datetime | None = None


@router.post("/incidents/{id}/review", response=MessageOut)
def review(request: HttpRequest, id: UUID, payload: ReviewIn | None = None) -> dict[str, str]:
    """«Lo he revisado»: closes an open event; a newer case reopens it."""
    get_object_or_404(OpsAlert.objects.using("owner"), pk=id)
    done = incident_kinds.review(
        id,
        actor=request.user.username,
        last_case_at=payload.last_case_at if payload is not None else None,
    )
    if not done.ok:
        raise ApiError("conflict", done.message, 409)
    return {"message": done.message}


@router.post("/incidents/{id}/discard-all", response=MessageOut)
def discard_all(request: HttpRequest, id: UUID) -> dict[str, str]:
    """«Descartar todos»: every undecided ambiguous send of an open `outbound_ambiguous`
    becomes `discarded` (nothing is sent) and the incident closes."""
    alert = get_object_or_404(OpsAlert.objects.using("owner"), pk=id)
    if alert.kind != "outbound_ambiguous" or alert.tenant_id is None:
        raise ApiError("conflict", "Solo para los envíos sin confirmar de un negocio.", 409)
    if alert.resolved_at is not None:
        raise ApiError("conflict", "La incidencia ya está cerrada.", 409)
    return result(actions.discard_all(alert.tenant_id, actor=request.user.username))


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


@router.post("/outbound/{id}/discard", response=MessageOut)
def discard(request: HttpRequest, id: UUID) -> dict[str, str]:
    get_object_or_404(OutboundMessage.objects.using("owner"), pk=id)
    return result(actions.discard(id, actor=request.user.username))


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
