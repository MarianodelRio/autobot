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

from autobot.ops import check, containers, health, incidents, system
from autobot.ops.models import OpsAlert
from autobot.runtime.models import Contact, OutboundMessage
from autobot.tenancy.registry import get_registry
from autobot.tenancy.tx import tenant_tx
from tests.helpers.disk import fake_disk
from tests.helpers.integration import wa_tenant

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


def failed_send(created_at: datetime | None = None) -> OutboundMessage:
    tenant = get_registry().by_slug["wa"]
    with tenant_tx(tenant.id):
        contact, _ = Contact.objects.get_or_create(
            tenant_id=tenant.id, channel="main", external_id="ES.test"
        )
        row = OutboundMessage.objects.create(
            tenant_id=tenant.id,
            contact=contact,
            idem_key=str(uuid7()),
            channel="main",
            kind="proactive",
            status="failed",
            last_error="status failed: 131047",
        )
    if created_at is not None:
        OutboundMessage.objects.using("owner").filter(id=row.id).update(created_at=created_at)
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


def test_an_event_whose_cases_are_gone_stays_open_with_no_cases(tenants: Any) -> None:
    tenants(wa_tenant())
    row = failed_send()
    check.run()
    assert incident().case_count == 1
    OutboundMessage.objects.using("owner").filter(id=row.id).update(status="sent")
    check.run()
    assert incident().case_count == 0  # a person still closes it


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
