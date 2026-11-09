"""Tenant mutations use the audited configuration store."""

import json
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from django.core.cache import cache
from django.db import connections
from pytest_django import Settings

from autobot.ops.models import AuditEvent, OpsAlert
from autobot.runtime.models import (
    Contact,
    Conversation,
    DemoEvent,
    DemoSession,
    InboundEvent,
    MetricEvent,
    Notification,
    OutboundMessage,
    OwnerLink,
)
from autobot.runtime.notifications import _cooldown_key
from autobot.tenancy.models import Tenant, TenantDatasetVersion, TenantSecret
from tests.helpers.integration import demo_tenant, tg_tenant, wa_tenant
from tests.platform.panel.conftest import HOST, get, post
from tests.platform.tenancy.helpers import TG_SECRETS, WA_SECRETS

NOW = datetime(2026, 11, 8, 12, tzinfo=UTC)

pytestmark = pytest.mark.django_db(transaction=True, databases=["default", "owner"])


def put(client: Any, path: str, data: dict[str, Any]) -> Any:
    return client.put(
        f"/api/panel/{path}", data=json.dumps(data), content_type="application/json", HTTP_HOST=HOST
    )


def test_writes_and_audit(authed_client: Any, tenants: Any) -> None:
    doc = wa_tenant("a")
    tenants(doc)
    created = post(
        authed_client,
        "tenants",
        {
            "pack": "toy",
            "slug": "new",
            "name": "New",
            "timezone": "Europe/Madrid",
            "channel_type": "telegram",
            "config": {},
        },
    )
    assert created.status_code == 200, created.content
    doc["name"] = "Updated"
    published = put(
        authed_client, "tenants/a/document", {"document": doc, "base_version": 1, "comment": "edit"}
    )
    assert published.status_code == 200, published.content
    assert published.json()["version"] == 2
    assert (
        post(authed_client, "tenants/a/rollback", {"version": 1, "comment": "undo"}).status_code
        == 200
    )
    assert post(authed_client, "tenants/a/status", {"action": "pause"}).status_code == 200
    assert put(authed_client, "tenants/a/secrets", {"secrets": WA_SECRETS}).status_code == 204
    actions = set(
        AuditEvent.objects.using("owner").filter(actor="operator").values_list("action", flat=True)
    )
    assert {
        "tenant.create",
        "tenant.publish",
        "tenant.rollback",
        "tenant.status",
        "tenant.secrets",
    } <= actions


def test_empty_comment_gets_a_default_text(authed_client: Any, tenants: Any) -> None:
    doc = wa_tenant("a")
    tenants(doc)
    doc["name"] = "Updated"
    published = put(
        authed_client, "tenants/a/document", {"document": doc, "base_version": 1, "comment": "  "}
    )
    assert published.status_code == 200, published.content
    event = AuditEvent.objects.using("owner").get(action="tenant.publish")
    assert event.details["comment"] == "Edición desde el panel"


def test_secrets_partial_update_keeps_the_rest(authed_client: Any, tenants: Any) -> None:
    tenants(wa_tenant("a"))
    assert put(authed_client, "tenants/a/secrets", {"secrets": WA_SECRETS}).status_code == 204
    status = get(authed_client, "tenants/a/secrets").json()
    assert all(field["set"] for field in status["fields"])

    changed = {**WA_SECRETS, "app_secret": "new-app-secret"}
    only_app_secret = {**{k: "" for k in WA_SECRETS}, "app_secret": changed["app_secret"]}
    assert put(authed_client, "tenants/a/secrets", {"secrets": only_app_secret}).status_code == 204
    from autobot.tenancy.crypto import decrypt
    from autobot.tenancy.models import TenantSecret

    row = TenantSecret.objects.using("owner").get(tenant__slug="a")
    decrypted = decrypt(bytes(row.ciphertext))
    assert decrypted["app_secret"] == "new-app-secret"
    assert decrypted["access_token"] == WA_SECRETS["access_token"]
    assert decrypted["verify_token"] == WA_SECRETS["verify_token"]


def test_secrets_responses_never_contain_values(authed_client: Any, tenants: Any) -> None:
    tenants(wa_tenant("a"))
    assert put(authed_client, "tenants/a/secrets", {"secrets": WA_SECRETS}).status_code == 204
    body = get(authed_client, "tenants/a/secrets").content.decode()
    for value in WA_SECRETS.values():
        assert value not in body


def test_secrets_all_blank_without_previous_secrets_requires_everything(
    authed_client: Any, tenants: Any
) -> None:
    tenants(wa_tenant("a"), secrets={})
    empty = {k: "" for k in WA_SECRETS}
    response = put(authed_client, "tenants/a/secrets", {"secrets": empty})
    assert response.status_code == 422


def test_secrets_all_blank_with_previous_secrets_changes_nothing(
    authed_client: Any, tenants: Any
) -> None:
    tenants(wa_tenant("a"))
    assert put(authed_client, "tenants/a/secrets", {"secrets": WA_SECRETS}).status_code == 204
    empty = {k: "" for k in WA_SECRETS}
    assert put(authed_client, "tenants/a/secrets", {"secrets": empty}).status_code == 204

    from autobot.tenancy.crypto import decrypt
    from autobot.tenancy.models import TenantSecret

    row = TenantSecret.objects.using("owner").get(tenant__slug="a")
    assert decrypt(bytes(row.ciphertext)) == WA_SECRETS


def test_telegram_webhook_registers_and_audits(
    authed_client: Any, tenants: Any, monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    tenants(tg_tenant())
    settings.PUBLIC_URL = "https://api.example.org/"

    def handle(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/setWebhook")
        return httpx.Response(200, json={"ok": True, "result": True})

    original = httpx.Client
    monkeypatch.setattr(
        "httpx.Client", lambda **kwargs: original(transport=httpx.MockTransport(handle))
    )
    response = post(authed_client, "tenants/tg/telegram-webhook", {})
    assert response.status_code == 200, response.content
    assert response.json()["url"] == "https://api.example.org/webhooks/telegram/pubtg0000"
    assert AuditEvent.objects.using("owner").filter(action="tenant.webhook_register").exists()


def test_telegram_webhook_requires_a_telegram_channel(authed_client: Any, tenants: Any) -> None:
    tenants(wa_tenant("a"))
    assert post(authed_client, "tenants/a/telegram-webhook", {}).status_code == 400


def test_telegram_webhook_failure_returns_502_without_the_token(
    authed_client: Any, tenants: Any, monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    tenants(tg_tenant())
    settings.PUBLIC_URL = "https://api.example.org/"

    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"ok": False, "error_code": 401})

    original = httpx.Client
    monkeypatch.setattr(
        "httpx.Client", lambda **kwargs: original(transport=httpx.MockTransport(handle))
    )
    response = post(authed_client, "tenants/tg/telegram-webhook", {})
    assert response.status_code == 502
    assert TG_SECRETS["bot_token"] not in response.content.decode()


def test_owner_invite_returns_the_link_once_without_the_code_in_audit(
    authed_client: Any, tenants: Any, monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    tenants(wa_tenant("a"))
    settings.NOTIFY_BOT_TOKEN = "123:NOTIFY-TOKEN"

    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": True, "result": {"username": "AvisosBot"}})

    original = httpx.Client
    monkeypatch.setattr(
        "httpx.Client", lambda **kwargs: original(transport=httpx.MockTransport(handle))
    )
    response = post(authed_client, "tenants/a/owner-invite", {})
    assert response.status_code == 200, response.content
    body = response.json()
    assert body["url"].startswith("https://t.me/AvisosBot?start=")
    code = body["url"].rsplit("=", 1)[1]
    event = AuditEvent.objects.using("owner").get(action="tenant.owner_invite")
    assert code not in json.dumps({"summary": event.summary, "details": event.details})


def test_delete_rejects_wrong_slug_demo_and_active(authed_client: Any, tenants: Any) -> None:
    tenants(tg_tenant(status="paused"), demo_tenant("demo"), wa_tenant("active"))
    assert post(authed_client, "tenants/tg/delete", {"confirm_slug": "wrong"}).status_code == 400
    assert post(authed_client, "tenants/demo/delete", {"confirm_slug": "demo"}).status_code == 400
    assert (
        post(authed_client, "tenants/active/delete", {"confirm_slug": "active"}).status_code == 409
    )
    assert Tenant.objects.using("owner").count() == 3


def _seed_everything(tenant_id: Any, other_id: Any) -> None:
    """One row of every customer-data table for `tenant_id`, plus a neighbor."""
    for tid in (tenant_id, other_id):
        contact = Contact.objects.using("owner").create(
            tenant_id=tid, channel="main", external_id=f"id-{tid}"
        )
        Conversation.objects.using("owner").create(tenant_id=tid, contact=contact, state={})
        inbound = InboundEvent.objects.using("owner").create(
            tenant_id=tid,
            channel="main",
            kind="message",
            provider_event_id=f"evt-{tid}",
            payload={},
            status="done",
            received_at=NOW,
        )
        OutboundMessage.objects.using("owner").create(
            tenant_id=tid,
            contact=contact,
            channel="main",
            kind="reply",
            idem_key=f"idem-{tid}",
            inbound_event=inbound,
            payload={},
            status="sent",
        )
        Notification.objects.using("owner").create(
            tenant_id=tid, idem_key=f"notif-{tid}", kind="daily", text="x"
        )
        MetricEvent.objects.using("owner").create(
            tenant_id=tid, kind="event", value=1, idem_key=f"metric-{tid}"
        )
        DemoSession.objects.using("owner").create(
            channel="demo_tg", external_id=f"demo-{tid}", tenant_id=tid, selected_at=NOW
        )
        OwnerLink.objects.using("owner").create(tenant_id=tid, chat_id=1, linked_at=NOW)
        TenantDatasetVersion.objects.using("owner").create(
            tenant_id=tid,
            name="timetable",
            version=1,
            files={"a.txt": "x"},
            sha256="0" * 64,
            author="operator",
        )
        OpsAlert.objects.using("owner").create(
            tenant_id=tid, kind=f"kind-{tid}", severity="warning", text="x", first_seen_at=NOW
        )
        AuditEvent.objects.using("owner").create(
            tenant_id=tid, actor="operator", action="test", summary="x", at=NOW
        )
        cache.set(f"health:{tid}", {"checked_at": 1})
        cache.set(f"runtime:{tid}:main", {"ok": True})
        cache.set(_cooldown_key(f"kind-{tid}", tid), True)
    DemoEvent.objects.using("owner").create(
        channel="demo_tg", provider_event_id=f"demo-{tenant_id}", payload={}, received_at=NOW
    )
    with connections["owner"].cursor() as cursor:
        cursor.execute(
            "INSERT INTO procrastinate_jobs(task_name, queue_name, status, args, attempts) "
            "VALUES ('send_message', 'outbound', 'todo', %s, 0)",
            [json.dumps({"tenant_id": str(tenant_id)})],
        )


def _stub_telegram_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": True, "result": True})

    original = httpx.Client
    monkeypatch.setattr(
        "httpx.Client", lambda **kwargs: original(transport=httpx.MockTransport(handle))
    )


def test_delete_erases_every_table_and_cache_key_leaving_the_neighbor_intact(
    authed_client: Any, tenants: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_telegram_ok(monkeypatch)
    tenants(tg_tenant(status="paused"), wa_tenant("other"))
    target = Tenant.objects.using("owner").get(slug="tg")
    other = Tenant.objects.using("owner").get(slug="other")
    tenant_id, other_id = target.id, other.id
    _seed_everything(tenant_id, other_id)

    response = post(authed_client, "tenants/tg/delete", {"confirm_slug": "tg"})
    assert response.status_code == 200, response.content

    with connections["owner"].cursor() as cursor:
        cursor.execute(
            "SELECT table_name FROM information_schema.columns "
            "WHERE table_schema = 'public' AND column_name = 'tenant_id'"
        )
        tables = [row[0] for row in cursor.fetchall()]
        assert tables  # sanity: the introspection itself still finds candidates
        for table in tables:
            cursor.execute(f'SELECT count(*) FROM "{table}" WHERE tenant_id = %s', [str(tenant_id)])
            assert cursor.fetchone()[0] == 0, f"{table} still has rows for the purged tenant"
            cursor.execute(f'SELECT count(*) FROM "{table}" WHERE tenant_id = %s', [str(other_id)])
            assert cursor.fetchone()[0] >= 1, f"{table} lost the neighbor's row"
        cursor.execute(
            "SELECT count(*) FROM procrastinate_jobs WHERE args->>'tenant_id' = %s",
            [str(tenant_id)],
        )
        assert cursor.fetchone()[0] == 0

    assert cache.get(f"health:{tenant_id}") is None
    assert cache.get(f"runtime:{tenant_id}:main") is None
    assert cache.get(_cooldown_key(f"kind-{tenant_id}", tenant_id)) is None
    assert cache.get(f"health:{other_id}") is not None

    assert not Tenant.objects.using("owner").filter(pk=tenant_id).exists()
    assert Tenant.objects.using("owner").filter(pk=other_id).exists()
    purge_events = list(AuditEvent.objects.using("owner").filter(action="tenant.purge"))
    assert len(purge_events) == 1
    assert purge_events[0].tenant_id is None
    assert purge_events[0].details["slug"] == "tg"

    from autobot.tenancy.registry import reset_registry

    reset_registry()
    assert get(authed_client, "tenants/tg").status_code == 404
    # The slug is free again.
    recreated = post(
        authed_client,
        "tenants",
        {
            "pack": "toy",
            "slug": "tg",
            "name": "Recreated",
            "timezone": "Europe/Madrid",
            "channel_type": "telegram",
            "config": {},
        },
    )
    assert recreated.status_code == 200, recreated.content


def test_delete_blocked_by_a_running_job_deletes_nothing(
    authed_client: Any, tenants: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_telegram_ok(monkeypatch)
    tenants(tg_tenant(status="paused"))
    tenant_id = Tenant.objects.using("owner").get(slug="tg").id
    with connections["owner"].cursor() as cursor:
        cursor.execute(
            "INSERT INTO procrastinate_jobs(task_name, queue_name, status, args, attempts) "
            "VALUES ('send_message', 'outbound', 'doing', %s, 0)",
            [json.dumps({"tenant_id": str(tenant_id)})],
        )
    response = post(authed_client, "tenants/tg/delete", {"confirm_slug": "tg"})
    assert response.status_code == 409, response.content
    assert Tenant.objects.using("owner").filter(pk=tenant_id).exists()
    assert TenantSecret.objects.using("owner").filter(tenant_id=tenant_id).exists()


def test_delete_continues_when_telegram_refuses_the_webhook_removal(
    authed_client: Any, tenants: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    tenants(tg_tenant(status="paused"))

    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"ok": False, "error_code": 401})

    original = httpx.Client
    monkeypatch.setattr(
        "httpx.Client", lambda **kwargs: original(transport=httpx.MockTransport(handle))
    )
    response = post(authed_client, "tenants/tg/delete", {"confirm_slug": "tg"})
    assert response.status_code == 200, response.content
    assert response.json()["telegram_webhook_removed"] is False
    assert not Tenant.objects.using("owner").exists()


def test_delete_rolls_back_everything_on_audit_failure(
    authed_client: Any, tenants: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_telegram_ok(monkeypatch)
    tenants(tg_tenant(status="paused"))
    tenant_id = Tenant.objects.using("owner").get(slug="tg").id

    def fail(**kwargs: Any) -> None:
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr("autobot.runtime.privacy.record", fail)
    with pytest.raises(RuntimeError):
        post(authed_client, "tenants/tg/delete", {"confirm_slug": "tg"})
    assert Tenant.objects.using("owner").filter(pk=tenant_id).exists()
    assert TenantSecret.objects.using("owner").filter(tenant_id=tenant_id).exists()


def test_rejections(authed_client: Any, tenants: Any) -> None:
    doc = wa_tenant("a")
    tenants(doc, demo_tenant("demo"))
    conflict = put(
        authed_client, "tenants/a/document", {"document": doc, "base_version": 999, "comment": ""}
    )
    assert conflict.status_code == 409
    assert post(authed_client, "tenants/a/status", {"action": "offboard"}).status_code == 400
    assert put(authed_client, "tenants/demo/secrets", {"secrets": WA_SECRETS}).status_code == 400
    doc["timezone"] = "sensitive-invalid-value"
    invalid = put(
        authed_client, "tenants/a/document", {"document": doc, "base_version": 1, "comment": ""}
    )
    assert invalid.status_code == 422
    assert invalid.json()["details"]
    assert "sensitive-invalid-value" not in invalid.content.decode()
