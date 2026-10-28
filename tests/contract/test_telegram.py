"""Contract of the Telegram adapter against updates and answers in the
Bot API format (tests/fixtures/telegram/), and its use by the conversation harness."""

import dataclasses
import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
import pytest
from django.test import RequestFactory

from autobot.channels.base import Ambiguous, InboundItem, Rejected, RetryLater, Sent, parse_stored
from autobot.channels.telegram import TelegramAdapter
from autobot.channels.telegram.adapter import overflow
from autobot.channels.testing import check_rendering
from autobot.tenancy.schema import TelegramSecrets
from core.conversation import global_command
from core.proactive import ProactiveMessage, TemplateSpec
from core.replies import Button, Buttons, List, Row, Section, Text
from core.testing import Conversation
from tests.toy_pack import pack as toy

FIXTURES = Path(__file__).parent.parent / "fixtures" / "telegram"
SECRETS = TelegramSecrets.model_validate(
    {"bot_token": "123:SECRET-TOKEN", "webhook_secret": "w" * 32}
)
OUTBOUND_ID = UUID("01920000-0000-7000-8000-0000000000b1")
ADAPTER = TelegramAdapter()


def load(name: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((FIXTURES / name).read_text())
    return data


def only(name: str) -> InboundItem:
    (item,) = ADAPTER.parse(load(name), None)
    assert isinstance(item, InboundItem)
    return item


# ── verify ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("header", "ok"),
    [("w" * 32, True), ("w" * 31, False), ("x" * 32, False), ("ñ", False), (None, False)],
)
def test_verify_compares_the_secret_token(header: str | None, ok: bool) -> None:
    headers = {"X-Telegram-Bot-Api-Secret-Token": header} if header is not None else {}
    request = RequestFactory().post(
        "/webhooks/telegram/x", data=b"{}", content_type="application/json", headers=headers
    )
    assert ADAPTER.verify(request, None, SECRETS) is ok


# ── parse ─────────────────────────────────────────────────────────────────


def test_text_message() -> None:
    item = only("message.json")
    assert (item.provider_event_id, item.external_id, item.display_name, item.phone) == (
        "810000001",
        "100000001",
        "Lucía",
        None,
    )
    assert item.message.type == "text"
    assert item.message.text == "Hola, ¿a qué hora sale el bus?"
    assert item.message.received_at == datetime.fromtimestamp(1791194400, UTC)
    assert item.payload == load("message.json")


def test_start_is_text_and_the_runtime_reads_it_as_menu() -> None:
    message = only("start.json").message
    assert (message.type, message.text) == ("text", "/start")
    assert global_command(message) == "menu"


def test_callback_query_is_a_button() -> None:
    item = only("callback_query.json")
    assert (item.provider_event_id, item.external_id) == ("810000003", "100000001")
    assert (item.message.type, item.message.payload) == ("button", "greet")


def test_sticker_is_unsupported() -> None:
    assert only("sticker.json").message.type == "unsupported"


def test_groups_are_ignored() -> None:
    assert ADAPTER.parse(load("group.json"), None) == []
    callback = load("callback_query.json")
    callback["callback_query"]["message"]["chat"] = {"id": -100, "type": "group"}
    assert ADAPTER.parse(callback, None) == []


@pytest.mark.parametrize(
    "change",
    [
        lambda u: u.pop("update_id"),
        lambda u: u.update(update_id="1"),
        lambda u: u["message"]["from"].update(is_bot=True),
        lambda u: u["message"].pop("from"),
        lambda u: u["message"].pop("date"),
        lambda u: u["message"].update(text="   "),
        lambda u: u.update(edited_message=u.pop("message")),
    ],
)
def test_malformed_or_foreign_updates_give_nothing(change: Any) -> None:
    update = load("message.json")
    change(update)
    assert ADAPTER.parse(update, None) == []


def test_text_is_truncated_and_long_callback_data_dropped() -> None:
    update = load("message.json")
    update["message"]["text"] = "a" * 5000
    (item,) = ADAPTER.parse(update, None)
    assert isinstance(item, InboundItem)
    assert item.message.text == "a" * 4096
    callback = load("callback_query.json")
    callback["callback_query"]["data"] = "x" * 65
    assert ADAPTER.parse(callback, None) == []


@pytest.mark.parametrize(
    "name", ["message.json", "start.json", "sticker.json", "callback_query.json"]
)
def test_stored_payload_parses_back_to_the_same_item(name: str) -> None:
    (item,) = ADAPTER.parse(load(name), None)
    again = parse_stored(ADAPTER, json.loads(json.dumps(item.payload)), None)
    assert isinstance(item, InboundItem) and isinstance(again, InboundItem)
    if name == "callback_query.json":  # no date of its own: the time of each parse
        again = dataclasses.replace(
            again, message=dataclasses.replace(again.message, received_at=item.message.received_at)
        )
    assert again == item


# ── acknowledge ───────────────────────────────────────────────────────────


def client_answering(
    answer: httpx.Response | Exception, seen: list[httpx.Request] | None = None
) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        if isinstance(answer, Exception):
            raise answer
        return answer

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_acknowledge_answers_the_callback_query() -> None:
    seen: list[httpx.Request] = []
    adapter = TelegramAdapter(client_answering(httpx.Response(200, json={"ok": True}), seen))
    adapter.acknowledge(load("callback_query.json"), None, SECRETS)
    (request,) = seen
    assert str(request.url) == "https://api.telegram.org/bot123:SECRET-TOKEN/answerCallbackQuery"
    assert json.loads(request.content) == {"callback_query_id": "4382bfdwdsb323b2d9"}


def test_acknowledge_does_nothing_for_messages_and_survives_failures(
    caplog: pytest.LogCaptureFixture,
) -> None:
    seen: list[httpx.Request] = []
    TelegramAdapter(client_answering(httpx.Response(200), seen)).acknowledge(
        load("message.json"), None, SECRETS
    )
    assert seen == []
    for answer in (httpx.ReadTimeout("slow"), httpx.Response(400, json=load("error_400.json"))):
        TelegramAdapter(client_answering(answer)).acknowledge(
            load("callback_query.json"), None, SECRETS
        )
    assert "SECRET-TOKEN" not in caplog.text


# ── render ────────────────────────────────────────────────────────────────

BASE = {"parse_mode": "HTML", "link_preview_options": {"is_disabled": True}}


def test_render_text_escapes_html_and_converts_bold() -> None:
    rendered = ADAPTER.render(Text("Hola *Lucía* <3 & cía. 2*3*4 = *24*, a * b * c"), None)
    assert rendered == {
        **BASE,
        "text": "Hola <b>Lucía</b> &lt;3 &amp; cía. 2*3*4 = <b>24</b>, a * b * c",
    }


@pytest.mark.parametrize(
    ("text", "html"),
    [
        ("*Horario de invierno*", "<b>Horario de invierno</b>"),
        ("(*ida*) y *vuelta*.", "(<b>ida</b>) y <b>vuelta</b>."),
        ("* nada *", "* nada *"),
        ("**", "**"),
        ("*a*b*", "*a*b*"),
    ],
)
def test_bold_follows_whatsapp(text: str, html: str) -> None:
    assert ADAPTER.render(Text(text), None)["text"] == html


def test_render_buttons_one_per_row_with_bold_header_and_no_footer() -> None:
    reply = Buttons("¿Qué *quieres*?", [Button("a", "Uno"), Button("b", "Dos")], "Menú <1>", "Pie")
    assert ADAPTER.render(reply, None) == {
        **BASE,
        "text": "<b>Menú &lt;1&gt;</b>\n¿Qué <b>quieres</b>?",
        "reply_markup": {
            "inline_keyboard": [
                [{"text": "Uno", "callback_data": "a"}],
                [{"text": "Dos", "callback_data": "b"}],
            ]
        },
    }


def test_render_list_puts_descriptions_in_the_text() -> None:
    reply = List(
        "Elige día",
        "Ver días",
        [
            Section("Semana", [Row("d1", "Lunes", "3 huecos"), Row("d2", "Martes")]),
            Section("Otra", [Row("d3", "Sale", "Sale a las 7:00")]),
        ],
        header="Días",
        footer="Pie",
    )
    assert ADAPTER.render(reply, None) == {
        **BASE,
        "text": "<b>Días</b>\nElige día\n\nLunes: 3 huecos",
        "reply_markup": {
            "inline_keyboard": [
                [{"text": "Lunes", "callback_data": "d1"}],
                [{"text": "Martes", "callback_data": "d2"}],
                [{"text": "Sale a las 7:00", "callback_data": "d3"}],
            ]
        },
    }


def test_render_proactive_fills_the_template_text() -> None:
    spec = TemplateSpec("reminder", "es_ES", "Tu cita es el *{1}* a las {2}", ["Sí", "No"])
    out = ProactiveMessage(spec, ["jueves", "17:00"], ["yes_1", "no_1"])
    assert ADAPTER.render(out, None) == {
        **BASE,
        "text": "Tu cita es el <b>jueves</b> a las 17:00",
        "reply_markup": {
            "inline_keyboard": [
                [{"text": "Sí", "callback_data": "yes_1"}],
                [{"text": "No", "callback_data": "no_1"}],
            ]
        },
    }


def test_template_parameters_are_filled_in_one_pass() -> None:
    spec = TemplateSpec("t", "es_ES", "Hola {1}, tu cita es a las {2} {3}", [])
    out = ProactiveMessage(spec, ["{2} & <b>", "17:00"], [])
    assert (
        ADAPTER.render(out, None)["text"] == "Hola {2} &amp; &lt;b&gt;, tu cita es a las 17:00 {3}"
    )


def test_length_is_counted_in_utf16() -> None:
    emoji = "😀"  # one code point, two UTF-16 units
    fits = Text(emoji * 2048)
    too_long = Text(emoji * 2049)
    assert overflow(fits) == []
    assert overflow(too_long) == ["message has 4098 UTF-16 units (max 4096)"]
    rendered = ADAPTER.render(too_long, None)
    assert rendered["text"] == emoji * 2048  # cut on a whole character


def test_list_descriptions_count_toward_the_length() -> None:
    rows = [Row(f"r{i}", f"Fila {i}", "d" * 72) for i in range(10)]
    reply = List("x" * 1024, "Ver", [Section(None, rows)], header="h" * 60)
    assert overflow(reply) == []
    long_body = Text("é" * 4096)
    assert overflow(long_body) == []


# ── send ──────────────────────────────────────────────────────────────────


def test_send_posts_sendmessage_with_the_chat_id() -> None:
    seen: list[httpx.Request] = []
    adapter = TelegramAdapter(
        client_answering(httpx.Response(200, json=load("send_ok.json")), seen)
    )
    rendered = adapter.render(Text("Hola"), None)
    assert adapter.send(rendered, "100000001", None, SECRETS, OUTBOUND_ID) == Sent("46")
    (request,) = seen
    assert str(request.url) == "https://api.telegram.org/bot123:SECRET-TOKEN/sendMessage"
    assert json.loads(request.content) == {**rendered, "chat_id": "100000001"}


@pytest.mark.parametrize(
    ("answer", "outcome"),
    [
        (httpx.Response(200, json=load("send_ok.json")), Sent("46")),
        (httpx.Response(200, json={"ok": True}), Ambiguous("2xx without a message_id")),
        (httpx.Response(401, json=load("error_401.json")), Rejected("HTTP 401, error 401", "auth")),
        (
            httpx.Response(403, json=load("error_403.json")),
            Rejected("HTTP 403, error 403", "recipient"),
        ),
        (
            httpx.Response(400, json=load("error_400.json")),
            Rejected("HTTP 400, error 400", "other"),
        ),
        (httpx.Response(429, json=load("error_429.json")), RetryLater(17.0)),
        (httpx.Response(429), RetryLater(None)),
        (httpx.Response(502), RetryLater(None)),
        (httpx.Response(500, json={"ok": False, "error_code": 500}), RetryLater(None)),
    ],
)
def test_send_outcome_table(answer: httpx.Response, outcome: object) -> None:
    adapter = TelegramAdapter(client_answering(answer))
    assert adapter.send({"text": "x"}, "1", None, SECRETS, OUTBOUND_ID) == outcome


@pytest.mark.parametrize(
    ("error", "outcome"),
    [
        (httpx.ReadTimeout("slow"), Ambiguous("ReadTimeout")),
        (httpx.RemoteProtocolError("cut"), Ambiguous("RemoteProtocolError")),
        (httpx.ConnectError("refused"), RetryLater()),
        (httpx.ConnectTimeout("no route"), RetryLater()),
        (httpx.PoolTimeout("pool full"), RetryLater()),
    ],
)
def test_network_errors(error: Exception, outcome: object) -> None:
    adapter = TelegramAdapter(client_answering(error))
    assert adapter.send({"text": "x"}, "1", None, SECRETS, OUTBOUND_ID) == outcome


def test_token_and_descriptions_are_never_logged(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    for answer in (
        httpx.Response(403, json=load("error_403.json")),
        httpx.ConnectError("https://api.telegram.org/bot123:SECRET-TOKEN/sendMessage"),
        httpx.ReadTimeout("https://api.telegram.org/bot123:SECRET-TOKEN/sendMessage"),
    ):
        TelegramAdapter(client_answering(answer)).send(
            {"text": "x"}, "1", None, SECRETS, OUTBOUND_ID
        )
    assert "SECRET-TOKEN" not in caplog.text
    assert "blocked" not in caplog.text


# ── The harness renders every scenario message with both adapters ─────────


def test_scenarios_are_rendered_with_both_adapters(monkeypatch: pytest.MonkeyPatch) -> None:
    from core.testing import harness

    rendered: list[object] = []
    monkeypatch.setattr(harness, "RENDER_CHECKS", [*harness.RENDER_CHECKS, rendered.append])
    chat = Conversation(toy.pack, channel="telegram")
    chat.send("hola")
    chat.press("color")
    chat.press("pick_1")  # a text reply and a proactive message
    assert len(rendered) == 4
    assert isinstance(rendered[-1], ProactiveMessage)


def test_a_reply_that_does_not_fit_telegram_fails_the_scenario() -> None:
    with pytest.raises(AssertionError, match="does not fit Telegram"):
        check_rendering(Text("😀" * 4000))
