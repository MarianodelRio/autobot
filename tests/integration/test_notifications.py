"""Notification delivery and ops cooldown with PostgreSQL and simulated Telegram."""

import json
from datetime import timedelta
from io import StringIO
from typing import Any

import httpx
import pytest
from django.core.cache import caches
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connections
from django.utils import timezone

from core.actions import NotifyOwner
from flowpilot.channels.adapters import TELEGRAM
from flowpilot.runtime import notifications, process
from flowpilot.runtime.models import Notification, PlatformCache
from flowpilot.runtime.outbound import SendRetry
from flowpilot.tenancy.registry import get_registry
from flowpilot.tenancy.tx import tenant_tx
from tests.integration.helpers import jobs, wa_tenant

pytestmark = [
    pytest.mark.django_db(transaction=True, databases=["default", "owner"]),
    pytest.mark.usefixtures("clean_jobs"),
]


@pytest.fixture
def telegram(settings: Any, monkeypatch: pytest.MonkeyPatch) -> Any:
    settings.NOTIFY_BOT_TOKEN = "notification-token"
    settings.OPS_TELEGRAM_CHAT_ID = "-200"

    def setup(*answers: Any) -> list[httpx.Request]:
        seen = []
        queue = list(answers)

        def handler(request: httpx.Request) -> httpx.Response:
            assert not connections["default"].in_atomic_block
            seen.append(request)
            answer = queue.pop(0)
            if isinstance(answer, Exception):
                raise answer
            assert isinstance(answer, httpx.Response)
            return answer

        monkeypatch.setattr(
            TELEGRAM, "client", httpx.Client(transport=httpx.MockTransport(handler))
        )
        return seen

    return setup


def ok() -> httpx.Response:
    return httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})


def notice(channel: str = "main", idem: str = "notice") -> Notification:
    tenant = get_registry().by_slug["wa"]
    with tenant_tx(tenant.id):
        process._notify_owner(tenant, channel, NotifyOwner("booking", "Hola <dueño>", idem))
        return Notification.objects.get(idem_key=idem)


def send(row: Notification, **kwargs: Any) -> None:
    notifications.send_notification(row.tenant_id, row.id, **kwargs)


def reload(row: Notification) -> Notification:
    return Notification.objects.using("owner").get(id=row.id)


def owner() -> dict[str, Any]:
    return wa_tenant(owner={"telegram_chat_id": 100, "notify": ["booking"]})


def test_delivery_once_and_job(tenants: Any, telegram: Any) -> None:
    tenants(owner())
    seen = telegram(ok())
    row = notice()
    assert notice().id == row.id
    queued = jobs()
    assert len(queued) == 1
    name, lock, args, queue = queued[0]
    assert (name, lock, queue) == ("send_notification", f"owner:{row.tenant_id}", "outbound")
    assert args == {"tenant_id": str(row.tenant_id), "notification_id": str(row.id)}
    send(row)
    send(row)
    assert len(seen) == 1
    assert "botnotification-token/" in str(seen[0].url)
    body = json.loads(seen[0].content)
    assert body["chat_id"] == "100" and "&lt;dueño&gt;" in body["text"]
    assert reload(row).status == "sent" and reload(row).sent_at is not None


@pytest.mark.parametrize("configured", [False, True])
def test_test_channel_always_routes_ops(tenants: Any, telegram: Any, configured: bool) -> None:
    tenants(owner() if configured else wa_tenant())
    seen = telegram(ok())
    row = notice("test")
    send(row)
    body = json.loads(seen[0].content)
    assert row.audience == "ops" and body["chat_id"] == "-200"
    assert body["text"].startswith("🧪 ")


@pytest.mark.parametrize("config", [None, {"telegram_chat_id": 100, "notify": []}])
def test_unsubscribed_only_logs(tenants: Any, telegram: Any, caplog: Any, config: Any) -> None:
    tenants(wa_tenant(owner=config))
    seen = telegram()
    tenant = get_registry().by_slug["wa"]
    with tenant_tx(tenant.id):
        process._notify_owner(tenant, "main", NotifyOwner("booking", "private", "n"))
    assert not Notification.objects.using("owner").exists() and not jobs() and not seen
    assert "only logged" in caplog.text and "private" not in caplog.text


@pytest.mark.parametrize("code", [429, 500, 503])
def test_safe_retry(tenants: Any, telegram: Any, code: int) -> None:
    tenants(owner())
    seen = telegram(httpx.Response(code, json={"parameters": {"retry_after": 7}}), ok())
    row = notice()
    with pytest.raises(SendRetry) as caught:
        send(row)
    assert caught.value.after_s == 7 and reload(row).status == "pending"
    send(row)
    assert reload(row).status == "sent" and len(seen) == 2


@pytest.mark.parametrize("answer", [httpx.ReadTimeout("secret"), httpx.Response(403)])
def test_ambiguous_or_rejected_never_retried(tenants: Any, telegram: Any, answer: Any) -> None:
    tenants(owner())
    seen = telegram(answer)
    row = notice()
    send(row)
    send(row)
    assert len(seen) == 1 and reload(row).status == "failed"


def test_final_retry_is_failed(tenants: Any, telegram: Any) -> None:
    tenants(owner())
    telegram(httpx.Response(500))
    row = notice()
    send(row, last_attempt=True)
    assert reload(row).status == "failed"


def test_crash_after_claim_never_resends(tenants: Any, telegram: Any) -> None:
    tenants(owner())
    seen = telegram(RuntimeError("interrupted"))
    row = notice()
    with pytest.raises(RuntimeError):
        send(row)
    send(row)
    assert len(seen) == 1 and reload(row).status == "failed"


def test_rls_wrong_tenant_does_not_send(tenants: Any, telegram: Any) -> None:
    tenants(owner(), wa_tenant("other"))
    seen = telegram()
    row = notice()
    notifications.send_notification(get_registry().by_slug["other"].id, row.id)
    assert not seen and reload(row).status == "pending"


def test_ops_cooldown_type_tenant_and_expiration(tenants: Any, telegram: Any) -> None:
    tenants(owner())
    seen = telegram(ok(), ok(), ok(), ok())
    tenant_id = get_registry().by_slug["wa"].id
    assert notifications.send_ops_alert("stuck", tenant_id, "Alerta")
    assert not notifications.send_ops_alert("stuck", tenant_id, "Alerta")
    assert notifications.send_ops_alert("failed", tenant_id, "Alerta")
    assert notifications.send_ops_alert("stuck", None, "Alerta")
    PlatformCache.objects.update(expires=timezone.now() - timedelta(seconds=1))
    assert notifications.send_ops_alert("stuck", tenant_id, "Alerta")
    assert len(seen) == 4 and not Notification.objects.using("owner").exists()


def test_unconfigured_does_not_send(tenants: Any, telegram: Any, settings: Any) -> None:
    tenants(owner())
    seen = telegram()
    settings.NOTIFY_BOT_TOKEN = ""
    row = notice()
    send(row)
    assert reload(row).status == "failed"
    assert not notifications.send_ops_alert("stuck", None, "alert") and not seen


def test_notify_link_private_matching_code(tenants: Any, telegram: Any, monkeypatch: Any) -> None:
    tenants(owner())
    monkeypatch.setattr(
        "flowpilot.management.commands.notify_link.secrets.token_urlsafe", lambda n: "code"
    )
    updates = [
        {
            "update_id": 1,
            "message": {"text": "/start wrong", "chat": {"id": 999, "type": "private"}},
        },
        {"update_id": 2, "message": {"text": "/start code", "chat": {"id": -1, "type": "group"}}},
        {
            "update_id": 3,
            "message": {
                "text": "/start code",
                "chat": {"id": 123, "type": "private"},
                "from": {"id": 123},
            },
        },
    ]
    seen = telegram(
        httpx.Response(200, json={"ok": True, "result": {"url": ""}}),
        httpx.Response(200, json={"ok": True, "result": {"username": "notify_bot"}}),
        httpx.Response(200, json={"ok": True, "result": updates}),
    )
    out = StringIO()
    call_command("notify_link", "wa", stdout=out)
    assert "owner.telegram_chat_id: 123" in out.getvalue()
    assert len(seen) == 3


def test_notify_link_webhook_refused(tenants: Any, telegram: Any) -> None:
    tenants(owner())
    seen = telegram(
        httpx.Response(200, json={"ok": True, "result": {"url": "https://example.com"}})
    )
    with pytest.raises(CommandError, match="sin webhook"):
        call_command("notify_link", "wa")
    assert len(seen) == 1


def test_ops_cooldown_concurrent_after_expiry(telegram: Any) -> None:
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    telegram(ok(), ok())
    assert notifications.send_ops_alert("concurrent", None, "Alerta")
    PlatformCache.objects.update(expires=timezone.now() - timedelta(seconds=1))
    barrier = Barrier(2)

    def check() -> bool:
        try:
            barrier.wait(timeout=10)
            return notifications.send_ops_alert("concurrent", None, "Alerta")
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(lambda _: check(), range(2))) == [False, True]


def test_notify_link_timeout(tenants: Any, telegram: Any, monkeypatch: Any) -> None:
    tenants(owner())
    telegram(
        httpx.Response(200, json={"ok": True, "result": {"url": ""}}),
        httpx.Response(200, json={"ok": True, "result": {"username": "notify_bot"}}),
    )
    ticks = iter([0, 301])
    monkeypatch.setattr(
        "flowpilot.management.commands.notify_link.time.monotonic", lambda: next(ticks)
    )
    with pytest.raises(CommandError, match="caducado"):
        call_command("notify_link", "wa", stdout=StringIO())


def test_ops_cooldown_survives_cache_pressure(telegram: Any, monkeypatch: Any) -> None:
    monkeypatch.setattr(caches["default"], "_max_entries", 1)
    seen = telegram(ok(), ok(), ok())
    for kind in ("first", "second", "third"):
        assert notifications.send_ops_alert(kind, None, "Alerta")
    assert not notifications.send_ops_alert("first", None, "Alerta")
    assert len(seen) == 3
