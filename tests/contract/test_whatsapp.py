"""Contract of the WhatsApp adapter against webhook bodies in the
documented format (tests/fixtures/whatsapp/) and simulated Graph API answers."""

import hashlib
import hmac
import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
import pytest
from django.test import RequestFactory

from core.messages import IncomingMessage
from core.proactive import ProactiveMessage, TemplateSpec
from core.replies import Button, Buttons, List, Row, Section, Text
from flowpilot.channels.base import (
    Ambiguous,
    InboundItem,
    Rejected,
    RetryLater,
    Sent,
    StatusItem,
    parse_stored,
)
from flowpilot.channels.whatsapp import WhatsAppAdapter
from flowpilot.tenancy.schema import WhatsAppChannel, WhatsAppSecrets

FIXTURES = Path(__file__).parent.parent / "fixtures" / "whatsapp"
CHANNEL = WhatsAppChannel(
    type="whatsapp",
    public_id="k3v9w2q8",
    app_id="1234567890",
    waba_id="9876543210",
    phone_number_id="1122334455",
)
SECRETS = WhatsAppSecrets.model_validate(
    {"app_secret": "app-secret", "access_token": "token-123", "verify_token": "verify-me"}
)
OUTBOUND_ID = UUID("01920000-0000-7000-8000-0000000000b1")
BSUID = "ES.13491208655302741918"
RECEIVED = datetime.fromtimestamp(1791194400, UTC)
ADAPTER = WhatsAppAdapter()


def load(name: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((FIXTURES / name).read_text())
    return data


def only(name: str) -> InboundItem:
    (item,) = ADAPTER.parse(load(name), CHANNEL)
    assert isinstance(item, InboundItem)
    return item


# ── verify ────────────────────────────────────────────────────────────────


def signed(body: bytes, secret: str = "app-secret") -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


@pytest.mark.parametrize(
    ("header", "ok"),
    [
        (signed(b'{"a":1}'), True),
        (signed(b'{"a":1}', "other"), False),
        (signed(b'{"a":2}'), False),
        (signed(b'{"a":1}').removeprefix("sha256="), False),
        ("sha256=ñ", False),
        (None, False),
    ],
)
def test_verify_checks_the_hmac_of_the_raw_body(header: str | None, ok: bool) -> None:
    headers = {"X-Hub-Signature-256": header} if header is not None else {}
    request = RequestFactory().post(
        "/webhooks/whatsapp/x", data=b'{"a":1}', content_type="application/json", headers=headers
    )
    assert ADAPTER.verify(request, CHANNEL, SECRETS) is ok


@pytest.mark.parametrize(
    ("params", "answer"),
    [
        ({"hub.mode": "subscribe", "hub.verify_token": "verify-me", "hub.challenge": "42"}, "42"),
        ({"hub.mode": "subscribe", "hub.verify_token": "wrong", "hub.challenge": "42"}, None),
        ({"hub.mode": "unsubscribe", "hub.verify_token": "verify-me", "hub.challenge": "42"}, None),
        ({}, None),
    ],
)
def test_get_handshake(params: dict[str, str], answer: str | None) -> None:
    assert ADAPTER.verify_subscription(params, SECRETS) == answer


# ── parse ─────────────────────────────────────────────────────────────────


def test_text_message() -> None:
    item = only("text.json")
    assert item.provider_event_id.startswith("wamid.")
    assert item.external_id == BSUID  # the BSUID wins over the phone
    assert item.phone == "+34600000001"
    assert item.display_name == "Lucía"
    assert item.message == IncomingMessage("text", "Hola, quiero una cita", None, RECEIVED)


def test_button_and_list_replies_and_template_buttons_are_buttons() -> None:
    assert only("button_reply.json").message.payload == "menu_book"
    assert only("list_reply.json").message.payload == "day_2026-10-09"
    template = only("template_button.json").message
    assert (template.type, template.payload) == ("button", "reminder_confirm_abc123")


def test_bsuid_only_contact_has_no_phone() -> None:
    item = only("bsuid_only.json")
    assert (item.external_id, item.phone, item.display_name) == (BSUID, None, "Lucía")


def test_phone_is_the_id_when_there_is_no_bsuid() -> None:
    body = load("text.json")
    message = body["entry"][0]["changes"][0]["value"]["messages"][0]
    del message["from_user_id"]
    (item,) = ADAPTER.parse(body, CHANNEL)
    assert isinstance(item, InboundItem)
    assert (item.external_id, item.phone) == ("34600000001", "+34600000001")


def test_media_and_unknown_types_are_unsupported() -> None:
    items = ADAPTER.parse(load("unsupported.json"), CHANNEL)
    assert len(items) == 5
    for item in items:
        assert isinstance(item, InboundItem)
        assert item.message == IncomingMessage("unsupported", None, None, RECEIVED)


def test_delivered_status_with_pricing() -> None:
    (item,) = ADAPTER.parse(load("status_delivered.json"), CHANNEL)
    assert isinstance(item, StatusItem)
    assert item.provider_event_id == f"{item.provider_message_id}:delivered"
    assert item.outbound_ref == "01920000-0000-7000-8000-0000000000b1"
    assert (item.status, item.pricing_category, item.billable, item.error) == (
        "delivered",
        "service",
        True,
        None,
    )


def test_failed_status_keeps_the_error_code_only() -> None:
    (item,) = ADAPTER.parse(load("status_failed.json"), CHANNEL)
    assert isinstance(item, StatusItem)
    assert (item.status, item.error, item.billable) == ("failed", "131026", None)


def test_another_phone_number_id_is_dropped() -> None:
    other = CHANNEL.model_copy(update={"phone_number_id": "999"})
    assert ADAPTER.parse(load("text.json"), other) == []


def test_a_channel_without_phone_number_id_accepts_nothing() -> None:
    channel = CHANNEL.model_copy(update={"phone_number_id": None})
    body = load("text.json")
    del body["entry"][0]["changes"][0]["value"]["metadata"]
    assert ADAPTER.parse(body, channel) == []


def test_text_is_truncated_and_bad_items_are_dropped() -> None:
    body = load("text.json")
    value = body["entry"][0]["changes"][0]["value"]
    good = value["messages"][0]
    value["messages"] = [
        {**good, "id": "wamid.long", "text": {"body": "a" * 5000}},
        {**good, "id": "wamid.blank", "text": {"body": "   "}},
        {
            **good,
            "id": "wamid.noid",
            "type": "interactive",
            "interactive": {"type": "button_reply", "button_reply": {"id": "x" * 65}},
        },
        {**good, "id": "wamid.badsender", "from": "abc", "from_user_id": "nope"},
        {**good, "id": "wamid.notime", "timestamp": "soon"},
        {**good, "id": "wamid.system", "type": "system", "system": {"body": "changed"}},
        {**good, "id": ""},
    ]
    (item,) = ADAPTER.parse(body, CHANNEL)
    assert isinstance(item, InboundItem)
    assert item.message.text == "a" * 4096


@pytest.mark.parametrize(
    "body", [{}, {"entry": "x"}, {"entry": [{"changes": [{"value": None}]}]}, {"entry": [1]}]
)
def test_malformed_bodies_give_nothing(body: dict[str, Any]) -> None:
    assert ADAPTER.parse(body, CHANNEL) == []


@pytest.mark.parametrize(
    "name",
    [
        "text.json",
        "button_reply.json",
        "list_reply.json",
        "template_button.json",
        "bsuid_only.json",
        "status_delivered.json",
        "status_failed.json",
    ],
)
def test_stored_payload_parses_back_to_the_same_item(name: str) -> None:
    (item,) = ADAPTER.parse(load(name), CHANNEL)
    stored = json.loads(json.dumps(item.payload))  # through jsonb
    assert parse_stored(ADAPTER, stored, CHANNEL) == item


def test_each_message_of_a_batch_stores_its_own_payload() -> None:
    items = ADAPTER.parse(load("unsupported.json"), CHANNEL)
    assert [parse_stored(ADAPTER, i.payload, CHANNEL) for i in items] == items


# ── render ────────────────────────────────────────────────────────────────


def test_render_text() -> None:
    assert ADAPTER.render(Text("Hola *Lucía*"), CHANNEL) == {
        "type": "text",
        "text": {"body": "Hola *Lucía*", "preview_url": False},
    }


def test_render_buttons() -> None:
    reply = Buttons("¿Qué quieres?", [Button("a", "Uno"), Button("b", "Dos")], "Cabecera", "Pie")
    assert ADAPTER.render(reply, CHANNEL) == {
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": "¿Qué quieres?"},
            "action": {
                "buttons": [
                    {"type": "reply", "reply": {"id": "a", "title": "Uno"}},
                    {"type": "reply", "reply": {"id": "b", "title": "Dos"}},
                ]
            },
            "header": {"type": "text", "text": "Cabecera"},
            "footer": {"text": "Pie"},
        },
    }


def test_render_list() -> None:
    reply = List(
        "Elige día",
        "Ver días",
        [Section(None, [Row("d1", "Lunes", "3 huecos"), Row("d2", "Martes")])],
    )
    assert ADAPTER.render(reply, CHANNEL) == {
        "type": "interactive",
        "interactive": {
            "type": "list",
            "body": {"text": "Elige día"},
            "action": {
                "button": "Ver días",
                "sections": [
                    {
                        "rows": [
                            {"id": "d1", "title": "Lunes", "description": "3 huecos"},
                            {"id": "d2", "title": "Martes"},
                        ]
                    }
                ],
            },
        },
    }


def test_render_template() -> None:
    spec = TemplateSpec("reminder", "es_ES", "Tu cita es el {1} a las {2}", ["Sí", "No"])
    out = ProactiveMessage(spec, ["jueves", "17:00"], ["yes_1", "no_1"])
    assert ADAPTER.render(out, CHANNEL) == {
        "type": "template",
        "template": {
            "name": "reminder",
            "language": {"code": "es_ES"},
            "components": [
                {
                    "type": "body",
                    "parameters": [
                        {"type": "text", "text": "jueves"},
                        {"type": "text", "text": "17:00"},
                    ],
                },
                {
                    "type": "button",
                    "sub_type": "quick_reply",
                    "index": "0",
                    "parameters": [{"type": "payload", "payload": "yes_1"}],
                },
                {
                    "type": "button",
                    "sub_type": "quick_reply",
                    "index": "1",
                    "parameters": [{"type": "payload", "payload": "no_1"}],
                },
            ],
        },
    }


# ── send ──────────────────────────────────────────────────────────────────


def adapter_answering(
    answer: httpx.Response | Exception, seen: list[httpx.Request] | None = None
) -> WhatsAppAdapter:
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        if isinstance(answer, Exception):
            raise answer
        return answer

    return WhatsAppAdapter(httpx.Client(transport=httpx.MockTransport(handler)))


def meta_error(status: int, code: int, **headers: str) -> httpx.Response:
    body = {
        "error": {
            "message": "(#131026) Message undeliverable to +34600000001",
            "type": "OAuthException",
            "code": code,
            "fbtrace_id": "Abc",
        }
    }
    return httpx.Response(status, json=body, headers=headers)


def test_send_posts_to_the_graph_api() -> None:
    seen: list[httpx.Request] = []
    ok = httpx.Response(
        200, json={"messaging_product": "whatsapp", "messages": [{"id": "wamid.X"}]}
    )
    adapter = adapter_answering(ok, seen)
    rendered = adapter.render(Text("hola"), CHANNEL)
    assert adapter.send(rendered, "+34600000001", CHANNEL, SECRETS, OUTBOUND_ID) == Sent("wamid.X")
    (request,) = seen
    assert str(request.url) == "https://graph.facebook.com/v23.0/1122334455/messages"
    assert request.headers["Authorization"] == "Bearer token-123"
    assert json.loads(request.content) == {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": "34600000001",
        "type": "text",
        "text": {"body": "hola", "preview_url": False},
        "biz_opaque_callback_data": str(OUTBOUND_ID),
    }


def test_send_to_a_bsuid_uses_recipient() -> None:
    seen: list[httpx.Request] = []
    ok = httpx.Response(200, json={"messages": [{"id": "wamid.Y"}]})
    adapter = adapter_answering(ok, seen)
    adapter.send({"type": "text", "text": {"body": "hola"}}, BSUID, CHANNEL, SECRETS, OUTBOUND_ID)
    body = json.loads(seen[0].content)
    assert body["recipient"] == BSUID
    assert "to" not in body


@pytest.mark.parametrize(
    ("answer", "outcome"),
    [
        (httpx.Response(200, json={"messages": [{"id": "wamid.Z"}]}), Sent("wamid.Z")),
        (httpx.Response(200, text="ok"), Ambiguous("2xx without a message id")),
        (meta_error(401, 0), Rejected("HTTP 401, error 0", "auth")),
        (meta_error(400, 190), Rejected("HTTP 400, error 190", "auth")),
        (meta_error(400, 131026), Rejected("HTTP 400, error 131026", "recipient")),
        (meta_error(400, 131030), Rejected("HTTP 400, error 131030", "recipient")),
        (meta_error(400, 100), Rejected("HTTP 400, error 100", "other")),
        (meta_error(403, 10), Rejected("HTTP 403, error 10", "other")),
        (httpx.Response(404), Rejected("HTTP 404", "other")),
        (meta_error(429, 130429, **{"Retry-After": "7"}), RetryLater(7.0)),
        (meta_error(429, 131056), RetryLater(None)),
        (meta_error(429, 130429, **{"Retry-After": "inf"}), RetryLater(None)),
        (meta_error(429, 130429, **{"Retry-After": "86400"}), RetryLater(3600.0)),
        (meta_error(500, 131000), RetryLater(None)),
        (meta_error(503, 131016), RetryLater(None)),
        (httpx.Response(502), Ambiguous("HTTP 502")),
        (httpx.Response(504, text="<html>Gateway Timeout</html>"), Ambiguous("HTTP 504")),
    ],
)
def test_send_outcome_table(answer: httpx.Response, outcome: object) -> None:
    adapter = adapter_answering(answer)
    assert adapter.send({}, "34600000001", CHANNEL, SECRETS, OUTBOUND_ID) == outcome


@pytest.mark.parametrize(
    ("error", "outcome"),
    [
        (httpx.ReadTimeout("slow"), Ambiguous("ReadTimeout")),
        (httpx.RemoteProtocolError("cut"), Ambiguous("RemoteProtocolError")),
        (httpx.WriteError("broken"), Ambiguous("WriteError")),
        (httpx.ConnectError("refused"), RetryLater()),
        (httpx.ConnectTimeout("no route"), RetryLater()),
        (httpx.PoolTimeout("pool full"), RetryLater()),
    ],
)
def test_network_errors(error: Exception, outcome: object) -> None:
    adapter = adapter_answering(error)
    assert adapter.send({}, "34600000001", CHANNEL, SECRETS, OUTBOUND_ID) == outcome


def test_send_without_phone_number_id_is_rejected() -> None:
    channel = CHANNEL.model_copy(update={"phone_number_id": None})
    outcome = WhatsAppAdapter().send({}, "34600000001", channel, SECRETS, OUTBOUND_ID)
    assert isinstance(outcome, Rejected)


def test_4xx_bodies_and_tokens_are_never_logged(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    adapter = adapter_answering(meta_error(400, 131026))
    outcome = adapter.send({}, "+34600000001", CHANNEL, SECRETS, OUTBOUND_ID)
    assert isinstance(outcome, Rejected)
    logged = caplog.text + outcome.reason
    for secret in ("Message undeliverable", "34600000001", "token-123", "Abc"):
        assert secret not in logged
    assert "131026" in caplog.text
