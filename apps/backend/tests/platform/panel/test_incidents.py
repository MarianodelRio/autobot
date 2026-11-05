# ruff: noqa: F811
"""HTTP contract for incident actions, listings and history cursors."""

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


@pytest.mark.usefixtures("clean_jobs")
def test_incident_listing_and_retry(authed_client: Any, message: OutboundMessage) -> None:
    ids = [
        queue_app().configure_task(name).defer(tenant_id=str(message.tenant_id), secret="hidden")
        for name in ("ops_check", "send_message")
    ]
    with connections["owner"].cursor() as db:
        db.execute("UPDATE procrastinate_jobs SET status='failed' WHERE id=ANY(%s)", [ids])
    now = timezone.now()
    for severity in ("notice", "critical", "warning"):
        OpsAlert.objects.using("owner").create(
            kind=severity, severity=severity, text="aviso", last_seen_at=now
        )
    data = get(authed_client, "incidents").json()
    assert [a["severity"] for a in data["alerts"]] == ["critical", "warning", "notice"]
    assert data["outbound"][0]["can_mark_sent"]
    assert data["outbound"][0]["can_resend"]
    assert all("last_event" in j for j in data["jobs"])
    assert post(authed_client, f"jobs/{ids[1]}/retry").status_code == 409
    assert post(authed_client, f"jobs/{ids[0]}/retry").status_code == 200
    assert ProcrastinateJob.objects.using("owner").get(pk=ids[0]).status == "todo"
    assert (
        AuditEvent.objects.using("owner").filter(action="job.retry", target_id=str(ids[0])).exists()
    )
    jobs = get(authed_client, "jobs?queue=default&limit=1").json()
    assert len(jobs["items"]) == 1
    assert jobs["next_cursor"]
    assert "secret" not in str(jobs)
    second = get(authed_client, "jobs?queue=default&limit=1&cursor=" + jobs["next_cursor"]).json()
    assert jobs["items"][0]["id"] != second["items"][0]["id"]


def test_alert_resolution_and_pagination(authed_client: Any) -> None:
    now = timezone.now()
    manual = OpsAlert.objects.using("owner").create(
        kind="manual", severity="warning", text="aviso", auto_resolves=False, last_seen_at=now
    )
    auto = OpsAlert.objects.using("owner").create(
        kind="auto", severity="critical", text="auto", last_seen_at=now
    )
    assert post(authed_client, f"alerts/{auto.id}/resolve").status_code == 400
    assert post(authed_client, f"alerts/{manual.id}/resolve").status_code == 200
    assert post(authed_client, f"alerts/{manual.id}/resolve").status_code == 409
    manual.refresh_from_db(using="owner")
    assert manual.resolved_by == "operator"
    assert (
        AuditEvent.objects.using("owner")
        .filter(action="alert.resolve", target_id=str(manual.id))
        .count()
        == 1
    )
    assert len(get(authed_client, "alerts?state=resolved").json()["items"]) == 1
    first = get(authed_client, "alerts?limit=1").json()
    second = get(authed_client, "alerts?limit=1&cursor=" + first["next_cursor"]).json()
    assert {first["items"][0]["id"], second["items"][0]["id"]} == {str(manual.id), str(auto.id)}
    for endpoint in ("alerts", "jobs", "audit"):
        assert get(authed_client, endpoint + "?cursor=bad").status_code == 400
    history = get(authed_client, "audit?action=alert.resolve").json()
    assert len(history["items"]) == 1
    assert history["items"][0]["actor"] == "operator"


@pytest.mark.usefixtures("clean_jobs")
def test_ineligible_sends_and_confirmation(authed_client: Any, message: OutboundMessage) -> None:
    endpoint = f"outbound/{message.id}/resend"
    for value in (False, None, "true", 1):
        assert post(authed_client, endpoint, {"confirm_duplicate_risk": value}).status_code == 400
    message.status = "failed"
    message.save(using="owner")
    row = get(authed_client, "incidents").json()["outbound"][0]
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
