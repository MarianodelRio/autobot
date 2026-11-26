"""The incident engine of ops_check (ADR-031): events counted after their review
watermark, reopening, the monthly billing event, container restarts and the counts that
drop when the cases are gone. PostgreSQL, real `send_ops_alert`, no Telegram."""

from datetime import datetime, timedelta
from typing import Any
from uuid import uuid7

import httpx
import pytest
from django.db import connections
from django.utils import timezone

from autobot.channels.base import Rejected
from autobot.ops import check, containers, health, incidents, system
from autobot.ops.models import OpsAlert
from autobot.runtime import outbound
from autobot.runtime.models import Channel, Contact, Notification, OutboundMessage, OwnerLink
from autobot.tenancy.registry import get_registry
from autobot.tenancy.tx import tenant_tx
from tests.helpers.disk import fake_disk
from tests.helpers.integration import demo_tenant, wa_tenant

pytestmark = [
    pytest.mark.django_db(transaction=True, databases=["default", "owner"]),
    pytest.mark.usefixtures("clean_jobs"),
]

REJECTED = "outbound_rejected:outside_window"


@pytest.fixture(autouse=True)
def quiet(monkeypatch: pytest.MonkeyPatch, settings: Any) -> None:
    settings.HEALTHCHECKS_PING_URL = ""
    settings.DEMO_TELEGRAM_TOKEN = ""
    settings.NOTIFY_BOT_TOKEN = ""
    settings.OPS_TELEGRAM_CHAT_ID = ""
    monkeypatch.setattr(health, "tenant_health", lambda tenant: [])
    for metric in ("memory", "load", "swap"):
        monkeypatch.setattr(system, metric, lambda: 1.0)
    fake_disk(monkeypatch, 1)


def failed_send(
    created_at: datetime | None = None,
    *,
    last_error: str = "status failed: 131047",
    status: str = "failed",
    channel: str = "main",
    slug: str = "wa",
) -> OutboundMessage:
    tenant = get_registry().by_slug[slug]
    with tenant_tx(tenant.id):
        contact, _ = Contact.objects.get_or_create(
            tenant_id=tenant.id, channel=channel, external_id="ES.test"
        )
        row = OutboundMessage.objects.create(
            tenant_id=tenant.id,
            contact=contact,
            idem_key=str(uuid7()),
            channel=channel,
            kind="proactive",
            status=status,
            last_error=last_error,
            failed_at=timezone.now() if status == "failed" else None,
        )
    if created_at is not None:
        OutboundMessage.objects.using("owner").filter(id=row.id).update(
            created_at=created_at, failed_at=created_at if status == "failed" else None
        )
    return row


def incident(kind: str = REJECTED) -> OpsAlert:
    return OpsAlert.objects.using("owner").get(kind=kind, resolved_at__isnull=True)


def test_a_rejected_send_is_an_event_reviewed_then_reopened(tenants: Any) -> None:
    tenants(wa_tenant())
    failed_send()
    failed_send()
    check.run()
    first = incident()
    assert not first.auto_resolves and first.case_count == 2 and first.severity == "warning"
    assert first.details == {"error_class": "outside_window"}
    check.run()  # still open, same row, recounted
    assert incident().id == first.id and incident().case_count == 2
    assert incidents.review(first.id, actor="ana").ok
    check.run()  # the same two cases: reviewed, nothing reopens
    assert not OpsAlert.objects.using("owner").filter(kind=REJECTED, resolved_at__isnull=True)
    failed_send()
    check.run()
    second = incident()
    assert second.id != first.id and second.case_count == 1  # only the new one
    (found,) = [i for i in incidents.open_incidents(using="owner") if i.row.kind == REJECTED]
    assert found.reopened and found.new_since_review == 1


def test_with_no_review_only_the_last_24_hours_count(tenants: Any) -> None:
    tenants(wa_tenant())
    failed_send(timezone.now() - timedelta(days=3))
    check.run()
    assert not OpsAlert.objects.using("owner").filter(kind=REJECTED).exists()


def test_an_event_whose_cases_are_gone_closes_itself(tenants: Any) -> None:
    """A rejected send later confirmed sent: no live case left, so the platform closes
    the event (`auto`, no review, watermark unchanged); a later case opens a new period."""
    tenants(wa_tenant())
    row = failed_send()
    check.run()
    first = incident()
    assert first.case_count == 1
    OutboundMessage.objects.using("owner").filter(id=row.id).update(status="sent")
    check.run()
    first.refresh_from_db(using="owner")
    assert first.resolved_at is not None and first.resolved_by == "auto"
    assert first.case_count == 0 and incidents.closed_how(first) == "auto"
    assert first.review_watermark is not None
    failed_send()
    check.run()
    second = incident()
    assert second.id != first.id and second.case_count == 1
    assert second.review_watermark == first.review_watermark
    (found,) = [i for i in incidents.open_incidents(using="owner") if i.row.kind == REJECTED]
    assert not found.reopened and found.new_since_review is None  # not a review


def test_a_just_reviewed_event_is_neither_zeroed_nor_closed_again(tenants: Any) -> None:
    tenants(wa_tenant())
    row = failed_send()
    check.run()
    first = incident()
    started = timezone.now()
    findings = check.collect(started)
    OutboundMessage.objects.using("owner").filter(id=row.id).update(status="sent")
    assert incidents.review(first.id, actor="ana").ok
    check.sync_alerts(findings, collected_at=started)
    first.refresh_from_db(using="owner")
    assert first.resolved_by == "ana" and first.case_count == 1


def test_a_review_between_collect_and_sync_does_not_reopen(tenants: Any) -> None:
    doc = wa_tenant()
    doc["channel"]["monthly_alert_threshold"] = 1
    tenants(doc)
    failed_send()
    billable_send()
    billable_send()
    check.run()
    started = timezone.now()
    findings = check.collect(started)  # counted before the review lands
    for kind in (REJECTED, "billing"):
        assert incidents.review(incident(kind).id, actor="ana").ok
    check.sync_alerts(findings, collected_at=started)
    assert not OpsAlert.objects.using("owner").filter(
        kind__in=(REJECTED, "billing"), resolved_at__isnull=True
    )


def billable_send(slug: str = "wa", channel: str = "main") -> None:
    tenant = get_registry().by_slug[slug]
    with tenant_tx(tenant.id):
        contact, _ = Contact.objects.get_or_create(
            tenant_id=tenant.id, channel=channel, external_id="ES.bill"
        )
        OutboundMessage.objects.create(
            tenant_id=tenant.id,
            contact=contact,
            idem_key=str(uuid7()),
            channel=channel,
            kind="reply",
            status="sent",
            billable=True,
            sent_at=timezone.now(),
        )


def test_a_resend_of_an_old_ambiguous_send_that_fails_is_a_new_case(tenants: Any) -> None:
    """Its case time is when it failed, not when its row was created days ago."""
    tenants(wa_tenant())
    tenant = get_registry().by_slug["wa"]
    old = timezone.now() - timedelta(days=3)
    row = failed_send(old, status="unknown", last_error="interrupted while sending")
    OpsAlert.objects.create(
        kind=REJECTED,
        tenant_id=tenant.id,
        severity="warning",
        text="old",
        auto_resolves=False,
        first_seen_at=old,
        review_watermark=timezone.now() - timedelta(hours=1),
        resolved_at=timezone.now() - timedelta(hours=1),
        resolved_by="ana",
    )
    with tenant_tx(tenant.id):
        message = OutboundMessage.objects.select_for_update().get(id=row.id)
        message.status = "sending"  # a person resent it
        outbound._record("wa", message, Rejected("HTTP 400, error 131047", "other"))
    stored = OutboundMessage.objects.using("owner").get(id=row.id)
    assert stored.status == "failed" and stored.failed_at is not None
    check.run()
    reopened = incident()
    assert reopened.case_count == 1 and reopened.last_case_at == stored.failed_at


def test_notice_classes_stay_in_the_panel_and_each_class_is_its_own_incident(
    tenants: Any,
) -> None:
    tenants(wa_tenant())
    failed_send()  # 131047: outside_window, 🟠
    failed_send(last_error="status failed: 131026")  # undeliverable, 🟡
    failed_send(last_error="auth: HTTP 401")  # the `auth` condition, not a rejected class
    check.run()
    assert incident(REJECTED).severity == "warning"
    undeliverable = incident("outbound_rejected:undeliverable")
    assert undeliverable.severity == "notice" and undeliverable.last_delivery == "panel"
    assert undeliverable.sent_count == 0
    assert not OpsAlert.objects.using("owner").filter(kind="outbound_rejected:auth").exists()
    assert incident("auth").auto_resolves


def test_a_lost_owner_notice_is_an_event_reviewed_then_reopened(
    tenants: Any, settings: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    tenants(wa_tenant())
    settings.NOTIFY_BOT_TOKEN = "notification-token"
    monkeypatch.setattr(health, "telegram_health", lambda *a, **k: [])
    tenant = get_registry().by_slug["wa"]
    OwnerLink.objects.create(tenant_id=tenant.id, chat_id=100, linked_at=timezone.now())

    def lost(idem: str) -> None:
        with tenant_tx(tenant.id):
            Notification.objects.create(
                tenant_id=tenant.id,
                idem_key=idem,
                kind="booking",
                text="x",
                status="failed",
                failed_at=timezone.now(),
            )

    lost("n1")
    check.run()
    first = incident("notification_failed")
    assert not first.auto_resolves and first.case_count == 1
    assert incidents.review(first.id, actor="ana").ok
    check.run()
    assert not OpsAlert.objects.using("owner").filter(
        kind="notification_failed", resolved_at__isnull=True
    )
    lost("n2")
    check.run()
    second = incident("notification_failed")
    assert second.id != first.id and second.case_count == 1
    (found,) = [
        i for i in incidents.open_incidents(using="owner") if i.row.kind == "notification_failed"
    ]
    assert found.reopened and found.new_since_review == 1


def job(task: str, status: str, event: str | None, at: datetime) -> int:
    with connections["owner"].cursor() as cursor:
        cursor.execute(
            "INSERT INTO procrastinate_jobs(task_name, queue_name, status, args)"
            " VALUES (%s, 'periodic', %s, '{}') RETURNING id",
            [task, status],
        )
        (job_id,) = cursor.fetchone() or (None,)
        if event is not None:
            cursor.execute(
                "INSERT INTO procrastinate_events(job_id, type, at) VALUES (%s, %s, %s)",
                [job_id, event, at],
            )
    assert job_id is not None
    return int(job_id)


def test_failed_jobs_are_one_event_per_task_and_aborted_ones_are_not(tenants: Any) -> None:
    tenants()
    now = timezone.now()
    job("ops_check", "failed", "failed", now - timedelta(minutes=5))
    job("ops_check", "failed", "failed", now - timedelta(minutes=3))
    job("ops_check", "aborted", "aborted", now)  # a stalled one superseded by a queued one
    job("run_periodic", "failed", "failed", now - timedelta(days=2))  # before the bootstrap
    check.run()
    row = incident("failed_job:ops_check")
    assert row.case_count == 2 and row.text.startswith("🟠 Trabajos fallidos: Comprobación")
    assert not OpsAlert.objects.using("owner").filter(kind="failed_job:run_periodic").exists()
    assert incidents.review(row.id, actor="ana").ok
    check.run()
    assert not OpsAlert.objects.using("owner").filter(
        kind="failed_job:ops_check", resolved_at__isnull=True
    )
    job("ops_check", "failed", "failed", timezone.now())
    check.run()
    assert incident("failed_job:ops_check").case_count == 1


def test_a_failed_job_retried_successfully_closes_its_event(tenants: Any) -> None:
    tenants()
    job_id = job("retention_cleanup", "failed", "failed", timezone.now() - timedelta(minutes=2))
    check.run()
    row = incident("failed_job:retention_cleanup")
    assert row.text == "🟠 Trabajos fallidos: Limpieza nocturna (1)."
    with connections["owner"].cursor() as cursor:
        cursor.execute("UPDATE procrastinate_jobs SET status = 'succeeded' WHERE id = %s", [job_id])
    check.run()
    row.refresh_from_db(using="owner")
    assert row.resolved_by == "auto" and row.case_count == 0


def test_billing_is_an_event_once_a_month(tenants: Any) -> None:
    doc = wa_tenant()
    doc["channel"]["monthly_alert_threshold"] = 1
    tenants(doc)
    tenant = get_registry().by_slug["wa"]
    with tenant_tx(tenant.id):
        contact = Contact.objects.create(tenant_id=tenant.id, channel="main", external_id="ES.b")
        for key in ("b1", "b2"):
            OutboundMessage.objects.create(
                tenant_id=tenant.id,
                contact=contact,
                idem_key=key,
                channel="main",
                kind="reply",
                status="sent",
                billable=True,
                sent_at=timezone.now(),
            )
    check.run()
    row = incident("billing")
    assert row.severity == "notice" and row.last_delivery == "panel"
    assert row.details["month"] == timezone.now().astimezone(tenant.info.timezone).strftime("%Y-%m")
    assert incidents.review(row.id, actor="ana").ok
    check.run()
    assert not OpsAlert.objects.using("owner").filter(kind="billing", resolved_at__isnull=True)
    # Next month: reviewed only for its own month, so it opens again.
    OpsAlert.objects.using("owner").filter(id=row.id).update(details={"month": "2000-01"})
    check.run()
    assert incident("billing").id != row.id


def test_the_demo_whatsapp_door_billing_is_a_monthly_event(tenants: Any, settings: Any) -> None:
    tenants(demo_tenant())
    settings.DEMO_WHATSAPP_MONTHLY_ALERT_THRESHOLD = 1
    billable_send("demo-toy", Channel.DEMO_WA)
    billable_send("demo-toy", Channel.DEMO_WA)
    check.run()
    row = incident("billing:demo_wa")
    assert row.tenant_id is None and row.severity == "notice" and not row.auto_resolves
    assert row.details["month"] == timezone.now().astimezone(check.MADRID).strftime("%Y-%m")
    assert incidents.review(row.id, actor="ana").ok
    check.run()
    assert not OpsAlert.objects.using("owner").filter(
        kind="billing:demo_wa", resolved_at__isnull=True
    )


def service(count: int, started_minutes_ago: float = 5) -> containers.ServiceState:
    return containers.ServiceState(
        service="web",
        name="autobot-web-1",
        status="running",
        health="healthy",
        restart_count=count,
        oom_killed=False,
        started_at=timezone.now() - timedelta(minutes=started_minutes_ago),
        image_tag="x",
        image_matches=None,
        level="ok",
        reason=None,
    )


def test_a_container_restart_is_an_event_when_its_count_grows(tenants: Any) -> None:
    tenants()
    now = timezone.now()
    # Never restarted, or restarted long ago with no incident yet: nothing.
    assert check._restart_findings([service(0)], now) == []
    assert check._restart_findings([service(3, started_minutes_ago=600)], now) == []
    (found,) = check._restart_findings([service(1)], now)
    assert found.case_count == 1 and found.details == {"restart_count": 1, "since": 0}
    check.sync_alerts([found])
    # The same count on the next pass: no new case.
    assert check._restart_findings([service(1)], now) == []
    (more,) = check._restart_findings([service(3)], now)
    assert more.case_count == 3 and more.details == {"restart_count": 3, "since": 0}
    check.sync_alerts([more])
    row = incident("container_restarted:web")
    assert incidents.review(row.id, actor="ana").ok
    # Recreated by a deploy: the count goes back to 0, only the stored count follows.
    assert check._restart_findings([service(0)], now) == []
    row.refresh_from_db(using="owner")
    assert row.details["restart_count"] == 0
    (again,) = check._restart_findings([service(1)], now)
    assert again.case_count == 1


def test_a_container_recreated_while_its_incident_is_open_keeps_counting(tenants: Any) -> None:
    tenants()
    now = timezone.now()
    for count in (1, 3):
        (found,) = check._restart_findings([service(count)], now)
        check.sync_alerts([found])
    assert incident("container_restarted:web").case_count == 3
    # Recreated (count back to 0) while open: `since` follows, nothing is lost.
    assert check._restart_findings([service(0)], now) == []
    (again,) = check._restart_findings([service(1)], now)
    assert again.case_count == 4 and again.details == {"restart_count": 1, "since": -3}
    check.sync_alerts([again])  # a negative count would break the CHECK constraint
    assert incident("container_restarted:web").case_count == 4


def test_a_failed_push_recovers_the_heartbeat_once_telegram_answers(
    tenants: Any, settings: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without the old 30-minute repeat, the hourly retry of an undelivered push is what
    turns `/fail` back into a success ping when the alert channel works again."""
    from autobot.channels.adapters import TELEGRAM

    tenants()
    settings.HEALTHCHECKS_PING_URL = "https://hc.invalid/ping/abc"
    settings.NOTIFY_BOT_TOKEN = "notification-token"
    settings.OPS_TELEGRAM_CHAT_ID = "-200"
    monkeypatch.setattr(health, "telegram_health", lambda *a, **k: [])  # the notify bot's
    pings: list[str] = []

    def ping(url: str, **_: Any) -> httpx.Response:
        pings.append(url)
        return httpx.Response(200)

    monkeypatch.setattr(httpx, "get", ping)
    answers = [
        httpx.Response(502),
        httpx.Response(200, json={"ok": True, "result": {"message_id": 1}}),
    ]

    def telegram(request: httpx.Request) -> httpx.Response:
        return answers.pop(0)

    monkeypatch.setattr(TELEGRAM, "client", httpx.Client(transport=httpx.MockTransport(telegram)))
    OpsAlert.objects.create(
        kind="deploy_rollback",
        severity="critical",
        text="🔴 Despliegue fallido",
        auto_resolves=False,
        last_delivery="failed",
        last_sent_at=timezone.now() - timedelta(minutes=30),
        first_seen_at=timezone.now() - timedelta(minutes=30),
    )
    check.run()  # retried less than an hour ago: not yet, and the channel is broken
    assert pings[-1].endswith("/fail")
    OpsAlert.objects.update(last_sent_at=timezone.now() - timedelta(hours=2))
    check.run()  # retried: Telegram still failing (502), still /fail
    assert pings[-1].endswith("/fail")
    OpsAlert.objects.update(last_sent_at=timezone.now() - timedelta(hours=2))
    check.run()  # retried: delivered, the heartbeat is healthy again
    assert pings[-1] == "https://hc.invalid/ping/abc"
    assert OpsAlert.objects.get(kind="deploy_rollback").last_delivery == "sent"
