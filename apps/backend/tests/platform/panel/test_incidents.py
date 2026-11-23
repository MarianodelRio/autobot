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


# ── Bulk resend after an incident (ADR-026) ──────────────────────────────


def spawn(message: OutboundMessage, n: int, status: str, **fields: Any) -> list[OutboundMessage]:
    fields.setdefault("kind", "reply")
    return [
        OutboundMessage.objects.using("owner").create(
            tenant=message.tenant,
            contact=message.contact,
            channel="main",
            idem_key=f"bulk:{status}:{i}:{fields.get('last_error', '')}",
            payload=message.payload,
            status=status,
            unknown_at=timezone.now() - timedelta(minutes=30) if status == "unknown" else None,
            **fields,
        )
        for i in range(n)
    ]


def bulk_jobs() -> int:
    return ProcrastinateJob.objects.using("owner").filter(task_name="send_message").count()


@pytest.mark.usefixtures("clean_jobs")
def test_bulk_resend_needs_step_up(authed_client: Any, message: OutboundMessage) -> None:
    response = post(
        authed_client,
        "outbound/resend-bulk",
        {"ids": [str(message.id)], "confirm_duplicate_risk": True},
    )
    assert response.status_code == 403 and response.json()["code"] == "reauth_required"
    message.refresh_from_db(using="owner")
    assert message.status == "unknown"


@pytest.mark.usefixtures("clean_jobs")
def test_bulk_resend_filters_preview_and_audit(
    reauthed_client: Any, message: OutboundMessage
) -> None:
    failed = spawn(message, 2, "failed")
    expired = spawn(message, 1, "expired", kind="proactive")
    spawn(message, 1, "sent")
    recent = spawn(message, 1, "unknown")[0]
    recent.unknown_at = timezone.now()
    recent.save(using="owner")
    tenant_id = str(message.tenant_id)

    preview = post(reauthed_client, "outbound/resend-bulk/preview", {"tenant_id": tenant_id}).json()
    assert preview == {"total": 5, "will_resend": 5, "cap": 500}  # message + 2 + 1 + recent
    only_failed = post(
        reauthed_client, "outbound/resend-bulk/preview", {"statuses": ["failed"]}
    ).json()
    assert only_failed["total"] == 2
    bad = post(reauthed_client, "outbound/resend-bulk/preview", {"statuses": ["sent"]})
    assert bad.status_code == 400

    no_confirm = post(reauthed_client, "outbound/resend-bulk", {"tenant_id": tenant_id})
    assert no_confirm.status_code == 400

    response = post(
        reauthed_client,
        "outbound/resend-bulk",
        {"tenant_id": tenant_id, "confirm_duplicate_risk": True},
    )
    assert response.status_code == 200, response.content
    body = response.json()
    # The recent unknown is left to resolve itself.
    assert (body["selected"], body["resent"], body["skipped"], body["over_cap"]) == (5, 4, 1, 0)
    for row in (*failed, *expired, message):
        row.refresh_from_db(using="owner")
        assert row.status == "pending" and row.expires_at is not None
        assert row.expires_at > timezone.now()
    assert bulk_jobs() == 4
    (start,) = AuditEvent.objects.using("owner").filter(action="outbound.resend_bulk_start")
    assert "5 mensajes" in start.summary and not start.target_id
    (event,) = AuditEvent.objects.using("owner").filter(action="outbound.resend_bulk")
    assert "4 reenviados" in event.summary and not event.target_id
    assert str(message.id) not in event.summary


@pytest.mark.usefixtures("clean_jobs")
def test_bulk_resend_cap_and_selection(
    reauthed_client: Any, message: OutboundMessage, monkeypatch: Any
) -> None:
    from autobot.ops import actions

    monkeypatch.setattr(actions, "BULK_CAP", 3)
    spawn(message, 5, "failed")
    preview = post(reauthed_client, "outbound/resend-bulk/preview", {"statuses": ["failed"]}).json()
    assert preview == {"total": 5, "will_resend": 3, "cap": 3}
    body = post(
        reauthed_client,
        "outbound/resend-bulk",
        {"statuses": ["failed"], "confirm_duplicate_risk": True},
    ).json()
    assert (body["resent"], body["over_cap"]) == (3, 2)
    too_many = post(
        reauthed_client,
        "outbound/resend-bulk",
        {"ids": [str(message.id)] * 4, "confirm_duplicate_risk": True},
    )
    assert too_many.status_code == 200  # duplicates collapse: one id
    over = post(
        reauthed_client,
        "outbound/resend-bulk",
        {
            "ids": [str(m.id) for m in spawn(message, 4, "failed", last_error="x")],
            "confirm_duplicate_risk": True,
        },
    )
    assert over.status_code == 400


def test_incidents_lists_held_notices(authed_client: Any, message: OutboundMessage) -> None:
    from autobot.runtime.models import Notification

    Notification.objects.using("owner").create(
        tenant=message.tenant, idem_key="h1", kind="booking", text="x", status="held"
    )
    data = get(authed_client, "incidents").json()
    assert data["held_notices"] == [
        {"tenant_id": str(message.tenant_id), "tenant": message.tenant.slug, "count": 1}
    ]


@pytest.mark.usefixtures("clean_jobs")
def test_bulk_resend_keeps_the_packs_deadline_and_drops_late_replies(
    reauthed_client: Any, message: OutboundMessage
) -> None:
    now = timezone.now()
    useful = spawn(
        message, 1, "expired", kind="proactive", not_after=now + timedelta(hours=2), last_error="a"
    )[0]
    obsolete = spawn(
        message, 1, "expired", kind="proactive", not_after=now - timedelta(hours=1), last_error="b"
    )[0]
    (late_reply,) = spawn(message, 1, "expired", last_error="c")
    # Rows from before `not_after` was stored: a short `expires_at` implies the deadline.
    legacy = spawn(
        message, 1, "expired", kind="proactive", expires_at=now - timedelta(hours=1), last_error="d"
    )[0]
    OutboundMessage.objects.using("owner").filter(pk=legacy.pk).update(
        created_at=now - timedelta(hours=5)
    )
    body = {"statuses": ["expired"]}
    preview = post(reauthed_client, "outbound/resend-bulk/preview", body).json()
    assert preview["total"] == 2  # the obsolete reminder and the late reply are not offered
    response = post(
        reauthed_client,
        "outbound/resend-bulk",
        {"ids": [str(m.id) for m in (useful, obsolete, late_reply, legacy)]}
        | {"confirm_duplicate_risk": True},
    ).json()
    assert (response["resent"], response["skipped"]) == (1, 3)
    useful.refresh_from_db(using="owner")
    assert useful.status == "pending"
    assert now < useful.expires_at <= now + timedelta(hours=2, seconds=5)  # type: ignore[operator]
    for row in (obsolete, late_reply, legacy):
        row.refresh_from_db(using="owner")
        assert row.status == "expired"


def test_bulk_resend_validates_its_input(reauthed_client: Any, message: OutboundMessage) -> None:
    ok = {"confirm_duplicate_risk": True}
    naive = post(reauthed_client, "outbound/resend-bulk/preview", {"since": "2026-01-01T00:00:00"})
    assert naive.status_code == 400
    reversed_ = post(
        reauthed_client,
        "outbound/resend-bulk",
        ok | {"since": "2026-02-01T00:00:00Z", "until": "2026-01-01T00:00:00Z"},
    )
    assert reversed_.status_code == 400
    too_long = post(
        reauthed_client,
        "outbound/resend-bulk",
        ok | {"ids": ["00000000-0000-0000-0000-000000000001"] * 501},
    )
    assert too_long.status_code in (400, 422)
