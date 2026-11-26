# ruff: noqa: F811
"""HTTP contract for incident actions, listings and history cursors."""

from datetime import timedelta
from typing import Any

import pytest
from django.db import connections
from django.utils import timezone
from procrastinate.contrib.django.models import ProcrastinateJob

from autobot.ops.actions import queue_app
from autobot.ops.models import AuditEvent, OpsAlert
from autobot.runtime.models import OutboundMessage
from tests.platform.panel.conftest import get, post
from tests.platform.runtime.test_actions import message  # noqa: F401

pytestmark = pytest.mark.django_db(transaction=True, databases=["default", "owner"])


@pytest.mark.usefixtures("clean_jobs")
@pytest.mark.parametrize("action,status", [("mark-sent", "sent"), ("resend", "pending")])
def test_send_actions(
    authed_client: Any, message: OutboundMessage, action: str, status: str
) -> None:
    endpoint = f"outbound/{message.id}/{action}"
    if action == "resend":
        assert post(authed_client, endpoint).status_code == 400
        assert post(authed_client, endpoint, {"confirm_duplicate_risk": False}).status_code == 400
    data = {"confirm_duplicate_risk": True}
    response = post(authed_client, endpoint, data)
    assert response.status_code == 200, response.content
    message.refresh_from_db(using="owner")
    assert message.status == status
    assert post(authed_client, endpoint, data).status_code == 409
    assert (
        AuditEvent.objects.using("owner")
        .filter(action="outbound." + action.replace("-", "_"), target_id=str(message.id))
        .count()
        == 1
    )


def test_discard_endpoint(authed_client: Any, message: OutboundMessage) -> None:
    endpoint = f"outbound/{message.id}/discard"
    assert post(authed_client, endpoint).status_code == 200
    message.refresh_from_db(using="owner")
    assert message.status == "discarded"
    assert post(authed_client, endpoint).status_code == 409
    assert (
        AuditEvent.objects.using("owner")
        .filter(action="outbound.discard", target_id=str(message.id))
        .count()
        == 1
    )
    assert (
        post(authed_client, "outbound/00000000-0000-0000-0000-000000000001/discard").status_code
        == 404
    )
    assert post(authed_client, "outbound/resend-bulk").status_code in (404, 405, 422)


def open_incident(kind: str, **fields: Any) -> OpsAlert:
    from autobot.ops.incidents import is_event

    now = timezone.now()
    defaults: dict[str, Any] = {
        "severity": "warning",
        "text": f"🟠 {kind}",
        "last_seen_at": now,
        "auto_resolves": not is_event(kind),
    }
    if is_event(kind):
        defaults["review_watermark"] = now - timedelta(hours=24)
    return OpsAlert.objects.using("owner").create(kind=kind, **{**defaults, **fields})


@pytest.mark.usefixtures("clean_jobs")
def test_incident_listing_with_cases_and_retry(
    authed_client: Any, message: OutboundMessage
) -> None:
    ids = [
        queue_app().configure_task(name).defer(tenant_id=str(message.tenant_id), secret="hidden")
        for name in ("ops_check", "send_message")
    ]
    now = timezone.now()
    with connections["owner"].cursor() as db:
        db.execute("UPDATE procrastinate_jobs SET status='failed' WHERE id=ANY(%s)", [ids])
        for job_id in ids:
            db.execute(
                "INSERT INTO procrastinate_events(job_id, type, at) VALUES (%s, 'failed', %s)",
                [job_id, now - timedelta(minutes=5)],
            )
    OutboundMessage.objects.using("owner").filter(id=message.id).update(
        unknown_at=now - timedelta(minutes=30)
    )
    for severity in ("notice", "critical", "warning"):
        open_incident(severity, severity=severity)
    open_incident("outbound_ambiguous", tenant_id=message.tenant_id, case_count=1)
    open_incident("failed_job:ops_check", case_count=1)
    open_incident("failed_job:send_message", case_count=1)
    data = get(authed_client, "incidents").json()
    assert data["total"] == 6
    assert data["by_severity"] == {"critical": 1, "warning": 4, "notice": 1}
    assert data["items"][0]["severity"] == "critical"
    assert data["items"][-1]["severity"] == "notice"
    by_kind = {item["kind"]: item for item in data["items"]}
    ambiguous = by_kind["outbound_ambiguous"]
    assert ambiguous["nature"] == "condition" and not ambiguous["reviewable"]
    assert ambiguous["tenant"] == message.tenant.slug and ambiguous["title"]
    (case,) = ambiguous["cases"]
    assert case["type"] == "send" and case["id"] == str(message.id)
    assert case["can_mark_sent"] and case["can_resend"] and case["can_discard"]
    (job_case,) = by_kind["failed_job:ops_check"]["cases"]
    assert job_case["type"] == "job" and job_case["task_label"] == "Comprobación de operación"
    assert job_case["can_retry"] and by_kind["failed_job:ops_check"]["reviewable"]
    (send_job,) = by_kind["failed_job:send_message"]["cases"]
    assert not send_job["can_retry"] and send_job["retry_reason"]
    assert post(authed_client, f"jobs/{ids[1]}/retry").status_code == 409
    assert post(authed_client, f"jobs/{ids[0]}/retry").status_code == 200
    assert ProcrastinateJob.objects.using("owner").get(pk=ids[0]).status == "todo"
    assert (
        AuditEvent.objects.using("owner").filter(action="job.retry", target_id=str(ids[0])).exists()
    )
    assert "secret" not in str(data)
    assert get(authed_client, "jobs").status_code == 404  # the unused listing was removed


def test_rejected_sends_are_cases_with_their_error_class(
    authed_client: Any, message: OutboundMessage
) -> None:
    OutboundMessage.objects.using("owner").filter(id=message.id).update(
        status="failed", last_error="recipient: HTTP 403, error 403", unknown_at=None
    )
    row = open_incident("outbound_rejected:blocked", tenant_id=message.tenant_id, case_count=1)
    (item,) = get(authed_client, "incidents").json()["items"]
    assert item["title"] == "Envíos rechazados: bot bloqueado"
    assert item["runbook"] == "/docs/incidencias/envios-unknown/#envios-rechazados"
    (case,) = item["cases"]
    assert case["error_class"] == "blocked" and case["error_title"] == "Bot bloqueado"
    assert not case["can_mark_sent"] and not case["can_discard"] and case["discard_reason"]
    # Reviewed: those cases are behind the watermark.
    assert post(authed_client, f"incidents/{row.id}/review").status_code == 200
    page = get(authed_client, f"incidents/{row.id}/cases").json()
    assert page["items"] == [] and page["next_cursor"] is None


def test_cases_are_paginated(authed_client: Any, message: OutboundMessage) -> None:
    from autobot.runtime.models import Contact

    contact = Contact.objects.using("owner").get(tenant_id=message.tenant_id)
    for i in range(3):
        OutboundMessage.objects.using("owner").create(
            tenant_id=message.tenant_id,
            contact=contact,
            channel="main",
            kind="reply",
            idem_key=f"page-{i}",
            status="unknown",
            unknown_at=timezone.now() - timedelta(hours=1),
        )
    row = open_incident("outbound_ambiguous", tenant_id=message.tenant_id)
    first = get(authed_client, f"incidents/{row.id}/cases?limit=2").json()
    second = get(
        authed_client, f"incidents/{row.id}/cases?limit=2&cursor={first['next_cursor']}"
    ).json()
    assert len(first["items"]) == 2 and len(second["items"]) == 1
    assert get(authed_client, f"incidents/{row.id}/cases?cursor=bad").status_code == 400


def test_review_closes_an_event_only(authed_client: Any) -> None:
    last_case = timezone.now() - timedelta(minutes=3)
    event = open_incident("deploy_rollback", severity="critical", last_case_at=last_case)
    condition = open_incident("disk")
    assert post(authed_client, f"incidents/{condition.id}/review").status_code == 409
    assert post(authed_client, f"incidents/{event.id}/review").status_code == 200
    assert post(authed_client, f"incidents/{event.id}/review").status_code == 409
    missing = "00000000-0000-0000-0000-000000000001"
    assert post(authed_client, f"incidents/{missing}/review").status_code == 404
    event.refresh_from_db(using="owner")
    # The newest case seen, never "now": a case that arrives meanwhile still reopens it.
    assert event.resolved_by == "operator" and event.review_watermark == last_case
    assert (
        AuditEvent.objects.using("owner")
        .filter(action="incident.review", target_id=str(event.id))
        .count()
        == 1
    )
    assert post(authed_client, f"alerts/{event.id}/resolve").status_code in (404, 405)
    assert [i["kind"] for i in get(authed_client, "incidents").json()["items"]] == ["disk"]


def test_history_says_how_each_one_closed(authed_client: Any) -> None:
    now = timezone.now()
    for kind, by in [("disk", "auto"), ("deploy_ok", "info"), ("deploy_rollback", "ana")]:
        severity = "info" if by == "info" else "warning"
        open_incident(kind, severity=severity, resolved_at=now, resolved_by=by)
    data = get(authed_client, "incidents/history").json()
    closed = {item["kind"]: (item["closed"], item["closed_by"]) for item in data["items"]}
    assert closed == {
        "disk": ("auto", None),
        "deploy_ok": ("info", None),
        "deploy_rollback": ("review", "ana"),
    }
    assert {item["severity"] for item in data["items"]} == {"warning", "info"}
    first = get(authed_client, "incidents/history?limit=1").json()
    assert len(first["items"]) == 1 and first["next_cursor"]
    for endpoint in ("incidents/history", "audit"):
        assert get(authed_client, endpoint + "?cursor=bad").status_code == 400


@pytest.mark.usefixtures("clean_jobs")
def test_ineligible_sends_and_confirmation(authed_client: Any, message: OutboundMessage) -> None:
    endpoint = f"outbound/{message.id}/resend"
    for value in (False, None, "true", 1):
        assert post(authed_client, endpoint, {"confirm_duplicate_risk": value}).status_code == 400
    message.status = "failed"
    message.save(using="owner")
    open_incident("outbound_rejected:other", tenant_id=message.tenant_id)
    row = get(authed_client, "incidents").json()["items"][0]["cases"][0]
    assert not row["can_mark_sent"] and row["mark_sent_reason"]
    assert not row["can_resend"] and row["resend_reason"]
    assert post(authed_client, endpoint, {"confirm_duplicate_risk": True}).status_code == 409
    assert post(authed_client, f"outbound/{message.id}/mark-sent").status_code == 409
    assert not AuditEvent.objects.using("owner").filter(target_id=str(message.id)).exists()


def test_audit_cursor_and_filters(authed_client: Any, tenants: Any) -> None:
    from autobot.tenancy.models import Tenant
    from tests.helpers.integration import tg_tenant

    tenants(tg_tenant())
    tenant = Tenant.objects.using("owner").get()
    now = timezone.now()
    records = [
        AuditEvent.objects.using("owner").create(
            at=now, actor="operator", action="test", summary="test", tenant_id=tenant.id
        )
        for _ in range(3)
    ]
    first = get(authed_client, f"audit?tenant={tenant.slug}&action=test&limit=2").json()
    second = get(
        authed_client,
        f"audit?tenant={tenant.slug}&action=test&limit=2&cursor=" + first["next_cursor"],
    ).json()
    assert [r["id"] for r in first["items"] + second["items"]] == [
        str(r.id) for r in reversed(records)
    ]
    assert second["next_cursor"] is None
    assert get(authed_client, "audit?tenant=missing").json()["items"] == []


def test_audit_actions(authed_client: Any) -> None:
    now = timezone.now()
    for action in ("zzz.action", "yyy.action", "yyy.action"):
        AuditEvent.objects.using("owner").create(
            at=now, actor="operator", action=action, summary="test"
        )
    actions = get(authed_client, "audit/actions").json()
    assert actions == sorted(set(actions))
    assert actions.count("yyy.action") == 1
    assert actions.index("yyy.action") < actions.index("zzz.action")


def test_held_notices_are_cases_of_owner_unlinked(
    authed_client: Any, message: OutboundMessage
) -> None:
    from autobot.runtime.models import Notification

    notice = Notification.objects.using("owner").create(
        tenant=message.tenant, idem_key="h1", kind="booking", text="x", status="held"
    )
    open_incident("owner_unlinked", tenant_id=message.tenant_id, severity="notice", case_count=1)
    data = get(authed_client, "incidents").json()
    assert "held_notices" not in data
    (item,) = data["items"]
    assert item["cases"] == [
        {
            "type": "notice",
            "id": str(notice.id),
            "status": "held",
            "created_at": item["cases"][0]["created_at"],
        }
    ]
    assert "x" not in [case.get("text") for case in item["cases"]]  # no notice text
