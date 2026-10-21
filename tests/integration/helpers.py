"""Shared helpers of the runtime integration tests: tenants written to a temporary
tenants/ and synced, webhook posts with valid credentials, and what ended up in the
inbound_event and procrastinate_jobs tables."""

import hashlib
import hmac
import itertools
import json
from pathlib import Path
from typing import Any

from django.db import connections
from django.test import Client

from flowpilot.runtime.models import InboundEvent
from tests.tenancy.helpers import TG_SECRETS, WA_SECRETS, tenant_yaml

FIXTURES = Path(__file__).parent.parent / "fixtures"
PHONE_NUMBER_ID = "1122334455"  # the one in tests/fixtures/whatsapp
BSUID = "ES.13491208655302741918"
WA_URL = "/webhooks/whatsapp/pubwa0000"
TG_URL = "/webhooks/telegram/pubtg0000"


def wa_tenant(slug: str = "wa", **changes: Any) -> dict[str, Any]:
    doc = tenant_yaml(slug, **changes)
    doc["channel"] = {
        "type": "whatsapp",
        "public_id": f"pub{slug}0000",
        "app_id": "1",
        "waba_id": "2",
        "phone_number_id": PHONE_NUMBER_ID if slug == "wa" else str(len(slug) * 111),
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
