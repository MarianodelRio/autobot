"""Hardening of the channel adapters: what the database cannot hold, what is not a
message from a person, absurd data and rate-limit answers."""

import json

import pytest

from autobot.channels.base import InboundItem, Rejected, RetryLater
from autobot.channels.payload import clean_payload, clean_text
from autobot.channels.telegram import TelegramAdapter
from autobot.channels.whatsapp import WhatsAppAdapter
from autobot.channels.whatsapp.adapter import RATE_LIMIT_ERRORS, classify
from tests.contract.test_telegram import load as load_tg
from tests.contract.test_whatsapp import CHANNEL, meta_error
from tests.contract.test_whatsapp import load as load_wa

WA = WhatsAppAdapter()
TG = TelegramAdapter()


# ── NUL and surrogates ────────────────────────────────────────────────────


def test_clean_text_and_payload() -> None:
    assert clean_text("a\x00b") == "ab"
    assert clean_text("a\ud800b") == "a�b"
    assert clean_text("plain ñ 📅") == "plain ñ 📅"
    value = {"k\x00": ["x\x00", 1, None, {"y": "z\x00"}], "ok": "fine"}
    assert clean_payload(value) == {"k": ["x", 1, None, {"y": "z"}], "ok": "fine"}
    untouched = {"a": ["b", {"c": 1}]}
    assert clean_payload(untouched) is untouched


def test_a_nul_in_a_whatsapp_text_or_name_is_removed_from_the_stored_payload() -> None:
    body = load_wa("text.json")
    value = body["entry"][0]["changes"][0]["value"]
    value["messages"][0]["text"]["body"] = "ho\x00la"
    value["contacts"][0]["profile"]["name"] = "Lu\x00cía"
    (item,) = WA.parse(body, CHANNEL)
    assert isinstance(item, InboundItem)
    assert item.message.text == "hola" and item.display_name == "Lucía"
    assert "\\u0000" not in json.dumps(item.payload)


def test_a_nul_in_a_telegram_text_or_name_is_removed_from_the_stored_payload() -> None:
    body = load_tg("message.json")
    body["message"]["text"] = "ho\x00la"
    body["message"]["from"]["first_name"] = "Lu\x00cía"
    (item,) = TG.parse(body, None)
    assert isinstance(item, InboundItem)
    assert item.message.text == "hola" and item.display_name == "Lucía"
    assert "\\u0000" not in json.dumps(item.payload)


# ── What is not a message from a person ───────────────────────────────────


@pytest.mark.parametrize("kind", ["reaction", "request_welcome", "system"])
def test_whatsapp_reactions_and_welcome_requests_are_ignored(kind: str) -> None:
    body = load_wa("text.json")
    message = body["entry"][0]["changes"][0]["value"]["messages"][0]
    message.pop("text")
    message["type"] = kind
    assert WA.parse(body, CHANNEL) == []


@pytest.mark.parametrize(
    "service", ["new_chat_members", "pinned_message", "new_chat_title", "left_chat_member"]
)
def test_telegram_service_messages_are_ignored(service: str) -> None:
    body = load_tg("message.json")
    body["message"].pop("text")
    body["message"][service] = {"x": 1}
    assert TG.parse(body, None) == []


@pytest.mark.parametrize("media", ["photo", "voice", "location", "document", "sticker"])
def test_telegram_media_is_unsupported_and_answered(media: str) -> None:
    body = load_tg("message.json")
    body["message"].pop("text")
    body["message"][media] = {"x": 1}
    (item,) = TG.parse(body, None)
    assert isinstance(item, InboundItem) and item.message.type == "unsupported"


@pytest.mark.parametrize("date", [10**20, -(10**15), 253402300800 * 10])
def test_telegram_absurd_dates_are_dropped_without_error(date: int) -> None:
    body = load_tg("message.json")
    body["message"]["date"] = date
    assert TG.parse(body, None) == []


# ── Meta's rate limits ────────────────────────────────────────────────────


@pytest.mark.parametrize("code", sorted(RATE_LIMIT_ERRORS))
@pytest.mark.parametrize("status", [400, 403, 429])
def test_rate_limit_codes_are_retried_even_with_a_4xx(code: int, status: int) -> None:
    assert classify(meta_error(status, code)) == RetryLater(None)


def test_rate_limit_codes_honour_retry_after() -> None:
    assert classify(meta_error(400, 130429, **{"Retry-After": "9"})) == RetryLater(9.0)


@pytest.mark.parametrize("code", [131047, 131049, 131048, 100])
def test_other_4xx_codes_are_never_retried(code: int) -> None:
    outcome = classify(meta_error(400, code))
    assert isinstance(outcome, Rejected) and outcome.kind == "other"


def test_the_auth_error_is_not_a_rate_limit() -> None:
    assert classify(meta_error(400, 190)) == Rejected("HTTP 400, error 190", "auth")


def test_unmodified_fixtures_are_not_changed_by_cleaning() -> None:
    body = load_wa("text.json")
    assert clean_payload(body) is body
