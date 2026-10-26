"""Shared helpers of the runtime integration tests: tenants written to a temporary
tenants/ and synced, webhook posts with valid credentials, and what ended up in the
inbound_event and procrastinate_jobs tables."""

import hashlib
import hmac
import itertools
import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from django.db import connections
from django.test import Client

from flowpilot.channels import adapters
from flowpilot.runtime import outbound, process
from flowpilot.runtime.models import DemoEvent, InboundEvent, OutboundMessage
from tests.tenancy.helpers import (
    TG_SECRETS,
    WA_SECRETS,
    demo_tenant_yaml,
    phone_number_id,
    tenant_yaml,
)

FIXTURES = Path(__file__).parent.parent / "fixtures"
PHONE_NUMBER_ID = "1122334455"  # the one in tests/fixtures/whatsapp
BSUID = "ES.13491208655302741918"
WA_URL = "/webhooks/whatsapp/pubwa0000"
TG_URL = "/webhooks/telegram/pubtg0000"
TELEGRAM_DEMO_URL = "/webhooks/telegram-demo"


def demo_tenant(slug: str = "demo-toy", **changes: Any) -> dict[str, Any]:
    return demo_tenant_yaml(slug, **changes)


def wa_tenant(slug: str = "wa", **changes: Any) -> dict[str, Any]:
    doc = tenant_yaml(slug, **changes)
    doc["channel"] = {
        "type": "whatsapp",
        "public_id": f"pub{slug}0000",
        "app_id": "1",
        "waba_id": "2",
        "phone_number_id": PHONE_NUMBER_ID if slug == "wa" else phone_number_id(slug),
    }
    return doc


def tg_tenant(slug: str = "tg", **changes: Any) -> dict[str, Any]:
    doc = tenant_yaml(slug, **changes)
    doc["channel"] = {"type": "telegram", "public_id": f"pub{slug}0000", "bot_username": "toy_bot"}
    doc["testers"] = {"main": ["100000001"]}
    return doc


def fixture(path: str) -> bytes:
    return (FIXTURES / path).read_bytes()


_COUNTER = itertools.count(1)


def wa_text(text: str) -> bytes:
    body = json.loads(fixture("whatsapp/text.json"))
    message = body["entry"][0]["changes"][0]["value"]["messages"][0]
    message["id"] = f"wamid.test{next(_COUNTER)}"
    message["text"] = {"body": text}
    return json.dumps(body).encode()


def wa_press(payload: str) -> bytes:
    body = json.loads(fixture("whatsapp/button_reply.json"))
    message = body["entry"][0]["changes"][0]["value"]["messages"][0]
    message["id"] = f"wamid.test{next(_COUNTER)}"
    message["interactive"]["button_reply"]["id"] = payload
    return json.dumps(body).encode()


def post_wa(body: bytes, secret: str = WA_SECRETS["app_secret"], ip: str = "203.0.113.1") -> int:
    signature = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    response = Client().post(
        WA_URL,
        data=body,
        content_type="application/json",
        headers={"X-Hub-Signature-256": signature},
        REMOTE_ADDR=ip,
    )
    return response.status_code


def post_tg(body: bytes, secret: str = TG_SECRETS["webhook_secret"], url: str = TG_URL) -> int:
    response = Client().post(
        url,
        data=body,
        content_type="application/json",
        headers={"X-Telegram-Bot-Api-Secret-Token": secret},
    )
    return response.status_code


def events() -> list[InboundEvent]:
    return list(InboundEvent.objects.using("owner").order_by("received_at"))


def jobs() -> list[tuple[str, str | None, dict[str, Any], str]]:
    with connections["owner"].cursor() as cursor:
        cursor.execute(
            "SELECT task_name, lock, args, queue_name FROM procrastinate_jobs ORDER BY id"
        )
        return [
            (n, lock, a if isinstance(a, dict) else json.loads(a), q)
            for n, lock, a, q in cursor.fetchall()
        ]


class Providers:
    """What was sent to Telegram (per bot token) and to Meta."""

    def __init__(self) -> None:
        self.telegram: list[tuple[str, dict[str, Any]]] = []
        self.meta: list[httpx.Request] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        if request.url.host == "graph.facebook.com":
            self.meta.append(request)
            return httpx.Response(200, json={"messages": [{"id": "wamid.X"}]})
        token, method = request.url.path.removeprefix("/bot").split("/")
        body = json.loads(request.content)
        self.telegram.append((f"{token}/{method}", body))
        return httpx.Response(200, json={"ok": True, "result": {"message_id": len(self.telegram)}})

    def texts(self, chat: int, token: str = "999:TEST-TOKEN") -> list[str]:
        return [
            body["text"]
            for where, body in self.telegram
            if where == f"{token}/sendMessage" and body["chat_id"] == str(chat)
        ]

    def buttons(self, chat: int) -> list[str]:
        sent = [
            b for w, b in self.telegram if w.endswith("sendMessage") and b["chat_id"] == str(chat)
        ]
        keyboard = sent[-1].get("reply_markup", {}).get("inline_keyboard", [])
        return [line[0]["callback_data"] for line in keyboard]


@pytest.fixture
def providers(monkeypatch: pytest.MonkeyPatch) -> Providers:
    found = Providers()
    client = httpx.Client(transport=httpx.MockTransport(found.handler))
    monkeypatch.setattr(adapters.TELEGRAM, "client", client)
    monkeypatch.setattr(adapters.WHATSAPP, "client", client)
    return found


def drain(**process_kwargs: Any) -> None:
    """Run what the worker would: route a demo door's events (if any), process and
    send, in order."""
    from flowpilot.channels.demo import selector

    for event in DemoEvent.objects.using("owner").filter(status="pending").order_by("received_at"):
        selector.route_demo_event(event.id)
    for inbound in (
        InboundEvent.objects.using("owner").filter(status="pending").order_by("received_at")
    ):
        process.process_event(inbound.tenant_id, inbound.id, last_attempt=False, **process_kwargs)
    for message in (
        OutboundMessage.objects.using("owner")
        .filter(status="pending")
        .order_by("created_at", "seq")
    ):
        outbound.send_message(message.tenant_id, message.id)
