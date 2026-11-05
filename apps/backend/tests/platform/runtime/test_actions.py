"""`autobot.ops.actions`: eligibility rules and mutations behind the panel's and the
operator commands' resolution of ambiguous sends and failed jobs. Previously tested
through the Admin's bulk actions in test_admin.py."""

from datetime import timedelta
from typing import Any

import httpx
import pytest
from django.utils import timezone
from procrastinate.contrib.django.models import ProcrastinateJob

from autobot.ops import actions, audit
from autobot.ops.models import AuditEvent
from autobot.runtime.models import Contact, OutboundMessage
from autobot.runtime.outbound import send_message
from autobot.tenancy.models import Tenant
from core.replies import Text
from core.serialization import dump_outbound
from tests.helpers.integration import tg_tenant

pytestmark = pytest.mark.django_db(transaction=True, databases=["default", "owner"])


@pytest.fixture
def message(tenants: Any) -> OutboundMessage:
    doc = tg_tenant()
    tenants(doc)
    tenant = Tenant.objects.using("owner").get(pk=doc["id"])
    contact = Contact.objects.using("owner").create(
        tenant=tenant, channel="main", external_id="100000001"
    )
    return OutboundMessage.objects.using("owner").create(
        tenant=tenant,
        contact=contact,
        channel="main",
        kind="reply",
        idem_key="test:unknown",
        payload=dump_outbound(Text("hola")),
        status="unknown",
        unknown_at=timezone.now() - timedelta(minutes=11),
        attempts=1,
    )


@pytest.mark.usefixtures("clean_jobs")
@pytest.mark.parametrize(
    "action,expected", [(actions.mark_sent, "sent"), (actions.resend, "pending")]
)
def test_resolve_unknown_is_audited(message: OutboundMessage, action: Any, expected: str) -> None:
    result = action(message.pk, actor="operator")
    assert result.ok
    message.refresh_from_db(using="owner")
    assert message.status == expected
    assert message.unknown_at is None
    assert AuditEvent.objects.using("owner").filter(target_id=str(message.pk)).count() == 1
    jobs = ProcrastinateJob.objects.using("owner").filter(task_name="send_message")
    assert jobs.count() == (1 if action is actions.resend else 0)
    if action is actions.resend:
        job = jobs.get()
        assert job.args == {"tenant_id": str(message.tenant_id), "outbound_id": str(message.pk)}
        assert job.lock.startswith("out:")
    # Resolving an already-resolved message is a no-op, not a second audit entry.
    assert not action(message.pk, actor="operator").ok
    assert AuditEvent.objects.using("owner").filter(target_id=str(message.pk)).count() == 1


@pytest.mark.parametrize("invalid", ["expired", "recent", "sent", "offboarded", "disabled"])
def test_invalid_unknown_cannot_be_resent(
    message: OutboundMessage, invalid: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from autobot.tenancy.registry import get_registry

    if invalid == "expired":
        message.payload = None
    elif invalid == "recent":
        message.unknown_at = timezone.now()
    elif invalid == "sent":
        message.status = "sent"
    elif invalid == "offboarded":
        Tenant.objects.using("owner").filter(pk=message.tenant_id).update(status="offboarded")
    else:
        get_registry().by_id[message.tenant_id].main_disabled.append("disabled")
    message.save(using="owner")
    assert not actions.resend(message.pk, actor="operator").ok
    assert not AuditEvent.objects.using("owner").filter(target_id=str(message.pk)).exists()


@pytest.mark.usefixtures("clean_jobs")
def test_mark_sent_ignores_tenant_and_payload_state(message: OutboundMessage) -> None:
    message.payload = None
    message.save(using="owner")
    Tenant.objects.using("owner").filter(pk=message.tenant_id).update(status="offboarded")
    assert actions.mark_sent(message.pk, actor="operator").ok
    message.refresh_from_db(using="owner")
    assert message.status == "sent"
    assert AuditEvent.objects.using("owner").filter(target_id=str(message.pk)).exists()
    assert not ProcrastinateJob.objects.using("owner").filter(task_name="send_message").exists()


@pytest.mark.usefixtures("clean_jobs")
def test_authorized_resend_sends_once(
    message: OutboundMessage, monkeypatch: pytest.MonkeyPatch
) -> None:
    from django.db import connections

    from autobot.channels import adapters

    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert not connections["default"].in_atomic_block
        assert not connections["owner"].in_atomic_block
        seen.append(request)
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 100}})

    monkeypatch.setattr(
        adapters.TELEGRAM, "client", httpx.Client(transport=httpx.MockTransport(handler))
    )
    assert actions.resend(message.pk, actor="operator").ok
    job = ProcrastinateJob.objects.using("owner").get(task_name="send_message")
    assert job.args["outbound_id"] == str(message.pk)
    send_message(message.tenant_id, message.pk)
    send_message(message.tenant_id, message.pk)
    message.refresh_from_db(using="owner")
    assert message.status == "sent"
    assert message.attempts == 2
    assert len(seen) == 1


@pytest.mark.usefixtures("clean_jobs")
def test_resend_rolls_back_state_job_and_audit(
    message: OutboundMessage, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr("autobot.ops.actions.audit.record", broken)
    with pytest.raises(RuntimeError, match="audit unavailable"):
        actions.resend(message.pk, actor="operator")
    message.refresh_from_db(using="owner")
    assert message.status == "unknown"
    assert not ProcrastinateJob.objects.using("owner").filter(task_name="send_message").exists()
    assert not AuditEvent.objects.using("owner").filter(target_id=str(message.pk)).exists()


@pytest.mark.usefixtures("clean_jobs")
def test_job_retry_is_conservative_and_audited() -> None:
    from django.db import connections

    from autobot.ops.actions import queue_app

    ids = []
    for name in ("ops_check", "send_message", "send_notification", "ops_check"):
        pk = queue_app().configure_task(name).defer()
        ids.append(pk)
    with connections["owner"].cursor() as cursor:
        cursor.execute("UPDATE procrastinate_jobs SET status='failed' WHERE id = ANY(%s)", [ids])
    with connections["owner"].cursor() as cursor:
        cursor.execute("UPDATE procrastinate_jobs SET status='doing' WHERE id=%s", [ids[-1]])
    results = [actions.retry_job(pk, actor="operator") for pk in ids]
    assert results[0].ok
    assert not results[1].ok  # send_message: delivery failure, never a blind retry
    assert not results[2].ok  # send_notification: same
    assert not results[3].ok  # not "failed" (status="doing")
    assert ProcrastinateJob.objects.using("owner").get(pk=ids[0]).status == "todo"
    assert (
        ProcrastinateJob.objects.using("owner").filter(pk__in=ids[1:3], status="failed").count()
        == 2
    )
    assert AuditEvent.objects.using("owner").filter(target_id=str(ids[0])).count() == 1
    assert ProcrastinateJob.objects.using("owner").get(pk=ids[-1]).status == "doing"


def test_can_retry_rejects_an_unregistered_task(monkeypatch: pytest.MonkeyPatch) -> None:
    from autobot.ops.actions import queue_app

    pk = queue_app().configure_task("ops_check").defer()
    from django.db import connections

    with connections["owner"].cursor() as cursor:
        cursor.execute(
            "UPDATE procrastinate_jobs SET status='failed', task_name='gone' WHERE id=%s", [pk]
        )
    job = ProcrastinateJob.objects.using("owner").get(pk=pk)
    ok, reason = actions.can_retry(job)
    assert not ok
    assert reason


@pytest.mark.parametrize("key", ["token", "bot_token", "webhook_secret", "otp"])
def test_audit_record_rejects_forbidden_keys(key: str) -> None:
    with pytest.raises(ValueError, match="secret-shaped"):
        audit.record(actor="t", action="t.test", summary="s", details={key: "x"})


def test_audit_record_rejects_forbidden_keys_nested() -> None:
    with pytest.raises(ValueError, match="secret-shaped"):
        audit.record(actor="t", action="t.test", summary="s", details={"outer": {"password": "x"}})


def test_audit_record_accepts_ordinary_details() -> None:
    audit.record(actor="t", action="t.test", summary="s", details={"fields": ["a", "b"]})
    assert AuditEvent.objects.using("owner").filter(action="t.test").exists()
