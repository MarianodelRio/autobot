"""Exercise the real password/TOTP/session path and owner transactions under runtime RLS."""

from datetime import timedelta
from typing import Any

import httpx
import pytest
from django.contrib.admin.models import LogEntry
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import connections
from django.test import Client
from django.test.utils import CaptureQueriesContext
from django.urls import URLResolver
from django.utils import timezone
from django_otp.oath import totp  # type: ignore[import-untyped]
from django_otp.plugins.otp_totp.models import TOTPDevice  # type: ignore[import-untyped]
from procrastinate.contrib.django.models import ProcrastinateJob

from autobot.admin import queue_app
from autobot.admin_db import admin_request
from autobot.channels import adapters
from autobot.runtime.models import Contact, OutboundMessage
from autobot.runtime.outbound import send_message
from autobot.tenancy.models import Tenant
from config.urls import internal, public
from core.replies import Text
from core.serialization import dump_outbound
from tests.integration.helpers import tg_tenant

pytestmark = pytest.mark.django_db(transaction=True, databases=["default", "owner"])


@pytest.fixture
def operator() -> tuple[Any, Any]:
    user = (
        get_user_model()
        .objects.db_manager("owner")
        .create_superuser("operator", "operator@example.invalid", "a-long-operator-password")
    )
    device = TOTPDevice.objects.using("owner").create(user=user, name="operator", confirmed=True)
    return user, device


def login(client: Client, device: Any, **extra: Any) -> Any:
    return client.post(
        "/admin/login/",
        {
            "username": "operator",
            "password": "a-long-operator-password",
            "otp_device": device.persistent_id,
            "otp_token": str(totp(device.bin_key)).zfill(device.digits),
            **extra,
        },
    )


@pytest.fixture
def logged(operator: tuple[Any, Any]) -> Client:
    client = Client()
    assert login(client, operator[1]).status_code == 302
    return client


def test_real_otp_owner_only_and_replay(operator: tuple[Any, Any]) -> None:
    client = Client()
    # Replay the exact same code even if the requests cross a TOTP time window.
    token = str(totp(operator[1].bin_key)).zfill(operator[1].digits)
    with CaptureQueriesContext(connections["default"]) as runtime:
        assert login(client, operator[1], otp_token=token).status_code == 302
        index = client.get("/admin/")
        assert index.status_code == 200
        assert "/admin/estado/" in index.content.decode()
        assert client.get("/admin/estado/").status_code == 200
    assert list(runtime) == []
    assert not admin_request.get()
    assert login(Client(), operator[1], otp_token=token).status_code == 200
    assert login(Client(), operator[1], otp_token="").status_code == 200
    assert login(Client(), operator[1], otp_token="invalid").status_code == 200


def test_authenticated_without_otp_is_denied(operator: tuple[Any, Any]) -> None:
    client = Client()
    client.force_login(operator[0])
    assert client.get("/admin/").status_code == 302
    assert client.get("/admin/estado/").status_code == 302
    assert all(str(route.pattern) != "admin/" for route in public)
    assert any(
        isinstance(route, URLResolver) and str(route.pattern) == "admin/" for route in internal
    )


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


def action(client: Client, message: OutboundMessage, name: str, **extra: Any) -> Any:
    return client.post(
        "/admin/autobot/outboundmessage/",
        {"action": name, "_selected_action": [str(message.pk)], "confirm": "yes", **extra},
    )


@pytest.mark.usefixtures("clean_jobs")
@pytest.mark.parametrize("name,expected", [("mark_sent", "sent"), ("resend", "pending")])
def test_resolve_unknown_owner_audited(
    logged: Client, message: OutboundMessage, name: str, expected: str
) -> None:
    assert not OutboundMessage.objects.exists()  # fp_app without tenant still sees zero rows
    with CaptureQueriesContext(connections["default"]) as runtime:
        assert action(logged, message, name).status_code == 302
    assert list(runtime) == []
    message.refresh_from_db(using="owner")
    assert message.status == expected
    assert message.unknown_at is None
    assert LogEntry.objects.using("owner").filter(object_id=str(message.pk)).count() == 1
    jobs = ProcrastinateJob.objects.using("owner").filter(task_name="send_message")
    assert jobs.count() == (1 if name == "resend" else 0)
    if name == "resend":
        job = jobs.get()
        assert job.args == {"tenant_id": str(message.tenant_id), "outbound_id": str(message.pk)}
        assert job.lock.startswith("out:")
        assert message.idem_key == "test:unknown"
    assert action(logged, message, name).status_code == 302
    assert LogEntry.objects.using("owner").filter(object_id=str(message.pk)).count() == 1


@pytest.mark.parametrize("invalid", ["expired", "recent", "sent", "offboarded", "disabled"])
def test_invalid_unknown_cannot_be_resolved(
    logged: Client, message: OutboundMessage, invalid: str, monkeypatch: pytest.MonkeyPatch
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
    assert action(logged, message, "resend").status_code == 302
    assert not LogEntry.objects.using("owner").filter(object_id=str(message.pk)).exists()


def test_confirmation_required(logged: Client, message: OutboundMessage) -> None:
    result = action(logged, message, "resend", confirm="")
    assert result.status_code == 200
    assert "duplicar" in result.content.decode()
    message.refresh_from_db(using="owner")
    assert message.status == "unknown"


@pytest.mark.usefixtures("clean_jobs")
def test_job_retry_is_conservative_and_audited(logged: Client) -> None:
    ids = []
    for name in ("ops_check", "send_message", "send_notification", "ops_check"):
        pk = queue_app().configure_task(name).defer()
        ids.append(pk)
    with connections["owner"].cursor() as cursor:
        cursor.execute("UPDATE procrastinate_jobs SET status='failed' WHERE id = ANY(%s)", [ids])
    with connections["owner"].cursor() as cursor:
        cursor.execute("UPDATE procrastinate_jobs SET status='doing' WHERE id=%s", [ids[-1]])
    result = logged.post(
        "/admin/procrastinate/procrastinatejob/",
        {"action": "retry", "_selected_action": ids},
    )
    assert result.status_code == 302
    assert ProcrastinateJob.objects.using("owner").get(pk=ids[0]).status == "todo"
    assert (
        ProcrastinateJob.objects.using("owner").filter(pk__in=ids[1:3], status="failed").count()
        == 2
    )
    assert LogEntry.objects.using("owner").filter(object_id=str(ids[0])).count() == 1
    assert logged.get(f"/admin/procrastinate/procrastinatejob/{ids[0]}/change/").status_code == 200
    assert ProcrastinateJob.objects.using("owner").get(pk=ids[-1]).status == "doing"


def test_panel_data(logged: Client, message: OutboundMessage) -> None:
    cache.set(f"runtime:{message.tenant_id}:main", {"last_sweep": "2026-10-25T10:00:00Z"}, None)
    cache.set(f"health:{message.tenant_id}", {"checked_at": 0, "issues": []}, None)
    result = logged.get("/admin/estado/")
    assert result.status_code == 200
    assert result.context_data is not None
    row = next(row for row in result.context_data["rows"] if row["channel"] == "main")
    assert row["tenant"] == "tg"
    assert row["outgoing"] == 1
    assert row["billable"] == 0
    assert row["last_sweep"] == "2026-10-25T10:00:00Z"
    assert row["health"]["stale"]


@pytest.mark.usefixtures("clean_jobs")
def test_authorized_resend_sends_once(
    logged: Client, message: OutboundMessage, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert not connections["default"].in_atomic_block
        assert not connections["owner"].in_atomic_block
        seen.append(request)
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 100}})

    monkeypatch.setattr(
        adapters.TELEGRAM, "client", httpx.Client(transport=httpx.MockTransport(handler))
    )
    assert action(logged, message, "resend").status_code == 302
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
    logged: Client, message: OutboundMessage, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr("autobot.admin.audit", broken)
    with pytest.raises(RuntimeError, match="audit unavailable"):
        action(logged, message, "resend")
    message.refresh_from_db(using="owner")
    assert message.status == "unknown"
    assert not ProcrastinateJob.objects.using("owner").filter(task_name="send_message").exists()
    assert not LogEntry.objects.using("owner").filter(object_id=str(message.pk)).exists()


def test_otp_failure_throttling_is_persistent(operator: tuple[Any, Any]) -> None:
    device = operator[1]
    assert login(Client(), device, otp_token="invalid").status_code == 200
    device.refresh_from_db(using="owner")
    assert device.throttling_failure_count == 1
    # A correct token immediately afterwards is throttled too.
    assert login(Client(), device).status_code == 200
    device.refresh_from_db(using="owner")
    assert device.last_t == -1


def test_resolution_requires_permission_and_csrf(
    logged: Client, message: OutboundMessage, operator: tuple[Any, Any]
) -> None:
    csrf_client = Client(enforce_csrf_checks=True)
    csrf_client.cookies = logged.cookies
    assert action(csrf_client, message, "resend").status_code == 403
    user = operator[0]
    user.is_superuser = False
    user.save(using="owner")
    result = action(logged, message, "resend")
    assert result.status_code == 403
    message.refresh_from_db(using="owner")
    assert message.status == "unknown"
    assert not LogEntry.objects.using("owner").filter(object_id=str(message.pk)).exists()


def test_panel_month_uses_tenant_timezone(
    logged: Client, message: OutboundMessage, monkeypatch: pytest.MonkeyPatch
) -> None:
    from datetime import UTC, datetime

    # October began at 22:00 UTC in Madrid; 22:30 is this month, 21:30 is not.
    monkeypatch.setattr(
        "autobot.admin.timezone.now", lambda: datetime(2026, 10, 1, 0, 30, tzinfo=UTC)
    )
    OutboundMessage.objects.using("owner").filter(pk=message.pk).update(
        created_at=datetime(2026, 9, 30, 22, 30, tzinfo=UTC),
        billable=True,
        sent_at=datetime(2026, 9, 30, 22, 31, tzinfo=UTC),
    )
    result = logged.get("/admin/estado/")
    assert result.context_data is not None
    main = next(row for row in result.context_data["rows"] if row["channel"] == "main")
    assert main["outgoing"] == 1 and main["billable"] == 1
    OutboundMessage.objects.using("owner").filter(pk=message.pk).update(
        created_at=datetime(2026, 9, 30, 21, 30, tzinfo=UTC)
    )
    result = logged.get("/admin/estado/")
    assert result.context_data is not None
    main = next(row for row in result.context_data["rows"] if row["channel"] == "main")
    assert main["outgoing"] == 0 and main["billable"] == 1
    OutboundMessage.objects.using("owner").filter(pk=message.pk).update(
        created_at=datetime(2026, 9, 30, 21, 30, tzinfo=UTC),
        sent_at=datetime(2026, 9, 30, 21, 31, tzinfo=UTC),
    )
    result = logged.get("/admin/estado/")
    assert result.context_data is not None
    main = next(row for row in result.context_data["rows"] if row["channel"] == "main")
    assert main["outgoing"] == 0 and main["billable"] == 0


@pytest.mark.usefixtures("clean_jobs")
def test_mark_sent_records_fact_after_payload_expired(
    logged: Client, message: OutboundMessage
) -> None:
    message.payload = None
    message.save(using="owner")
    Tenant.objects.using("owner").filter(pk=message.tenant_id).update(status="offboarded")
    assert action(logged, message, "mark_sent").status_code == 302
    message.refresh_from_db(using="owner")
    assert message.status == "sent"
    assert LogEntry.objects.using("owner").filter(object_id=str(message.pk)).exists()
    assert not ProcrastinateJob.objects.using("owner").filter(task_name="send_message").exists()
