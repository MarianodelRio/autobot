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
    # The retired bulk resend: no such route (not a validation error of a live one).
    assert post(authed_client, "outbound/resend-bulk").status_code in (404, 405)


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
    # «Avisos retenidos» is no list of its own any more: only the incidents.
    assert set(data) == {"items", "total", "by_severity"}
    (item,) = data["items"]
    # Exactly these keys: never the notice's text (it may name a customer).
    assert item["cases"] == [
        {
            "type": "notice",
            "id": str(notice.id),
            "status": "held",
            "created_at": item["cases"][0]["created_at"],
            "case_at": item["cases"][0]["created_at"],
        }
    ]
    assert item["has_cases"] and item["case_count"] == 1


def unknown_sends(message: OutboundMessage, n: int) -> None:
    from autobot.runtime.models import Contact

    contact = Contact.objects.using("owner").get(tenant_id=message.tenant_id)
    at = timezone.now() - timedelta(hours=1)
    for i in range(n):
        OutboundMessage.objects.using("owner").create(
            tenant_id=message.tenant_id,
            contact=contact,
            channel="main",
            kind="reply",
            idem_key=f"many-{i}",
            status="unknown",
            unknown_at=at - timedelta(seconds=i),
        )


def test_the_listing_counts_live_and_the_preview_continues_by_cursor(
    authed_client: Any, message: OutboundMessage
) -> None:
    OutboundMessage.objects.using("owner").filter(id=message.id).update(
        unknown_at=timezone.now() - timedelta(minutes=30)
    )
    unknown_sends(message, 21)  # 22 cases with `message`
    # ops_check's figures of its last pass are stale: the listing counts live.
    row = open_incident(
        "outbound_ambiguous", tenant_id=message.tenant_id, case_count=3, text="🟠 3 envíos"
    )
    open_incident("disk")
    by_kind = {i["kind"]: i for i in get(authed_client, "incidents").json()["items"]}
    item = by_kind["outbound_ambiguous"]
    assert item["has_cases"] and item["case_count"] == 22 and item["text"] == "🟠 3 envíos"
    assert item["can_discard_all"] and not by_kind["disk"]["can_discard_all"]
    assert len(item["cases"]) == 20 and item["cases_next_cursor"]
    assert not by_kind["disk"]["has_cases"] and by_kind["disk"]["cases_next_cursor"] is None
    rest = get(authed_client, f"incidents/{row.id}/cases?cursor={item['cases_next_cursor']}").json()
    ids = [c["id"] for c in item["cases"]] + [c["id"] for c in rest["items"]]
    assert len(rest["items"]) == 2 and rest["next_cursor"] is None and len(set(ids)) == 22
    assert len(get(authed_client, f"incidents/{row.id}/cases").json()["items"]) == 20


@pytest.mark.usefixtures("clean_jobs")
@pytest.mark.parametrize("action", ["discard", "mark-sent", "resend"])
def test_deciding_the_last_ambiguous_send_closes_the_condition_at_once(
    authed_client: Any, message: OutboundMessage, action: str
) -> None:
    row = open_incident("outbound_ambiguous", tenant_id=message.tenant_id, case_count=1)
    data = {"confirm_duplicate_risk": True}
    assert post(authed_client, f"outbound/{message.id}/{action}", data).status_code == 200
    row.refresh_from_db(using="owner")
    assert row.resolved_at is not None and row.resolved_by == "auto"
    assert get(authed_client, "incidents").json()["total"] == 0  # «Todo en orden»


def test_deciding_one_of_several_keeps_the_condition_open(
    authed_client: Any, message: OutboundMessage
) -> None:
    unknown_sends(message, 2)
    row = open_incident("outbound_ambiguous", tenant_id=message.tenant_id, case_count=3)
    assert post(authed_client, f"outbound/{message.id}/discard").status_code == 200
    row.refresh_from_db(using="owner")
    assert row.resolved_at is None and row.case_count == 2


def test_discard_all_discards_every_undecided_send_and_closes(
    authed_client: Any, message: OutboundMessage
) -> None:
    from autobot.runtime.models import Contact

    OutboundMessage.objects.using("owner").filter(id=message.id).update(
        unknown_at=timezone.now() - timedelta(minutes=30)
    )
    unknown_sends(message, 2)
    contact = Contact.objects.using("owner").get(tenant_id=message.tenant_id)
    OutboundMessage.objects.using("owner").create(
        tenant_id=message.tenant_id,
        contact=contact,
        channel="main",
        kind="reply",
        idem_key="recent",
        status="unknown",
        unknown_at=timezone.now(),  # still waiting for its status: not a case yet
    )
    row = open_incident("outbound_ambiguous", tenant_id=message.tenant_id, case_count=3)
    other = open_incident("outbound_rejected:other", tenant_id=message.tenant_id)
    assert post(authed_client, f"incidents/{other.id}/discard-all").status_code == 409
    response = post(authed_client, f"incidents/{row.id}/discard-all")
    assert response.status_code == 200, response.content
    statuses = dict(OutboundMessage.objects.using("owner").values_list("idem_key", "status"))
    assert statuses == {
        "test:unknown": "discarded",
        "many-0": "discarded",
        "many-1": "discarded",
        "recent": "unknown",
    }
    row.refresh_from_db(using="owner")
    assert row.resolved_by == "auto"
    (event,) = AuditEvent.objects.using("owner").filter(action="outbound.discard_all")
    assert event.details == {"count": 3} and event.tenant_id == message.tenant_id
    assert post(authed_client, f"incidents/{row.id}/discard-all").status_code == 409
    missing = "00000000-0000-0000-0000-000000000001"
    assert post(authed_client, f"incidents/{missing}/discard-all").status_code == 404


@pytest.mark.usefixtures("clean_jobs")
def test_retrying_the_last_failed_job_closes_its_event(
    authed_client: Any, message: OutboundMessage
) -> None:
    job_id = queue_app().configure_task("ops_check").defer()
    with connections["owner"].cursor() as db:
        db.execute("UPDATE procrastinate_jobs SET status='failed' WHERE id=%s", [job_id])
        db.execute(
            "INSERT INTO procrastinate_events(job_id, type, at) VALUES (%s, 'failed', %s)",
            [job_id, timezone.now() - timedelta(minutes=5)],
        )
    row = open_incident("failed_job:ops_check", case_count=1)
    assert post(authed_client, f"jobs/{job_id}/retry").status_code == 200
    row.refresh_from_db(using="owner")
    assert row.resolved_by == "auto" and incidents_closed_how(row) == "auto"


def incidents_closed_how(row: OpsAlert) -> str:
    from autobot.ops.incidents import closed_how

    return closed_how(row)


def test_review_never_covers_a_case_the_panel_did_not_show(authed_client: Any) -> None:
    now = timezone.now()
    stored = now - timedelta(minutes=1)
    shown = now - timedelta(minutes=10)
    event = open_incident("deploy_rollback", last_case_at=stored)
    body = {"last_case_at": shown.isoformat()}
    assert post(authed_client, f"incidents/{event.id}/review", body).status_code == 200
    event.refresh_from_db(using="owner")
    assert event.review_watermark == shown  # min(shown, stored)
    # Shown later than stored (never expected): the stored one bounds it.
    second = open_incident("deploy_aborted", last_case_at=shown)
    body = {"last_case_at": stored.isoformat()}
    assert post(authed_client, f"incidents/{second.id}/review", body).status_code == 200
    second.refresh_from_db(using="owner")
    assert second.review_watermark == shown


def test_review_watermark_edge_cases(authed_client: Any) -> None:
    now = timezone.now()
    previous = now - timedelta(minutes=2)
    # Never before the previous watermark of the key.
    event = open_incident(
        "deploy_rollback", last_case_at=now - timedelta(hours=1), review_watermark=previous
    )
    assert post(authed_client, f"incidents/{event.id}/review").status_code == 200
    event.refresh_from_db(using="owner")
    assert event.review_watermark == previous
    # No case time: the last time ops_check saw it.
    seen = now - timedelta(minutes=7)
    other = open_incident("deploy_aborted", last_case_at=None, last_seen_at=seen)
    assert post(authed_client, f"incidents/{other.id}/review").status_code == 200
    other.refresh_from_db(using="owner")
    assert other.review_watermark == seen


def test_every_count_of_open_incidents_agrees(authed_client: Any, tenants: Any) -> None:
    """GET /incidents, the sidebar (overview), the daily report and the tenant level read
    the same open incidents (ADR-031)."""
    from autobot.ops import report
    from autobot.ops.incidents import open_incidents
    from autobot.ops.status import tenant_status
    from autobot.panel.services.overview import build_overview
    from autobot.tenancy.registry import get_registry
    from tests.helpers.integration import wa_tenant

    tenants(wa_tenant())
    tenant = get_registry().by_slug["wa"]
    now = timezone.now()
    open_incident("outbound_rejected:outside_window", tenant_id=tenant.id, severity="warning")
    open_incident("disk", severity="critical")
    open_incident("billing", tenant_id=tenant.id, severity="notice")
    open_incident("deploy_rollback", resolved_at=now, resolved_by="ana")  # reviewed
    listed = get(authed_client, "incidents").json()
    overview = build_overview(now)
    status = report.platform_status(now)
    level = tenant_status(tenant, incidents=open_incidents(using="owner")).level
    assert listed["total"] == overview.incidents_open == len(status.incidents) == 3
    assert overview.status.level == status.level == "critical"
    assert level == "warning"
    (row,) = [r for r in overview.tenant_rows if r.slug == "wa"]
    assert row.health == "warning"
