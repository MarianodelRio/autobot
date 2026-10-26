"""Telegram Bot API adapter: lists and buttons map to inline keyboards. The same adapter serves a
business's own bot (`main` channel) and the platform's test bot: only the token
and the routing change.

The API URL carries the bot token: logs only hold exception names, status and error codes.
"""

import hmac
import html
import logging
import math
import re
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

import httpx
from django.http import HttpRequest

from core.limits import MAX_ID_BYTES, MAX_TEXT
from core.messages import IncomingMessage
from core.proactive import ProactiveMessage
from core.replies import Button, Buttons, List, Text
from core.serialization import Outbound
from flowpilot.channels.base import (
    Ambiguous,
    InboundItem,
    ParsedItem,
    Rejected,
    RetryLater,
    SendOutcome,
    Sent,
)
from flowpilot.tenancy.schema import TelegramChannel, TelegramSecrets

log = logging.getLogger(__name__)

API_URL = "https://api.telegram.org"
TIMEOUT_S = 10.0
SECRET_HEADER = "X-Telegram-Bot-Api-Secret-Token"
MAX_MESSAGE_UTF16 = 4096  # Telegram counts UTF-16 code units, after entity parsing
MAX_BUTTON_TEXT = 64
MAX_RETRY_AFTER_S = 3600.0
NO_PREVIEW = {"is_disabled": True}  # WhatsApp shows no link preview; Telegram does
# WhatsApp's *bold*: asterisks at word edges, with no space inside them ("2*3*4" and
# "a * b * c" stay as they are, as in WhatsApp).
BOLD = re.compile(r"(?<![\w*])\*(?=\S)([^*\n]*?\S)\*(?![\w*])")
PARAM = re.compile(r"\{(\d+)\}")

# `None` is the platform's test bot, which has no tenant.yaml channel.
type Channel = TelegramChannel | None


class TelegramAdapter:
    type: Literal["telegram"] = "telegram"

    def __init__(self, client: httpx.Client | None = None) -> None:
        self.client = client or httpx.Client(timeout=TIMEOUT_S)

    # ── Inbound ───────────────────────────────────────────────────────────

    def verify(self, request: HttpRequest, channel: Channel, secrets: TelegramSecrets) -> bool:
        """The `secret_token` given to setWebhook comes back in a header."""
        received = request.headers.get(SECRET_HEADER, "")
        expected = secrets.webhook_secret.get_secret_value()
        # As bytes: compare_digest raises on non-ASCII str (headers are decoded as latin-1).
        return hmac.compare_digest(received.encode(), expected.encode())

    def parse(self, body: dict[str, Any], channel: Channel) -> list[ParsedItem]:
        """One update → at most one item. Only private chats with people; groups,
        channels, bots and other update types are ignored."""
        update_id = body.get("update_id")
        if not isinstance(update_id, int) or isinstance(update_id, bool):
            return []
        message = body.get("message")
        callback = body.get("callback_query")
        if isinstance(message, dict):
            incoming = _message(message)
            sender = message.get("from")
            chat = message.get("chat")
        elif isinstance(callback, dict):
            incoming = _callback(callback)
            sender = callback.get("from")
            inner = callback.get("message")
            chat = inner.get("chat") if isinstance(inner, dict) else None
        else:
            return []
        if incoming is None or not _private(chat, sender):
            return []
        assert isinstance(sender, dict)  # checked by _private
        name = sender.get("first_name")
        return [
            InboundItem(
                provider_event_id=str(update_id),
                external_id=str(sender["id"]),
                display_name=name[:200] if isinstance(name, str) and name else None,
                phone=None,
                message=incoming,
                payload=body,
            )
        ]

    def acknowledge(
        self, payload: dict[str, Any], channel: Channel, secrets: TelegramSecrets
    ) -> None:
        """answerCallbackQuery, so the client stops showing the button as loading. A
        failure is logged and ignored."""
        callback = payload.get("callback_query")
        query_id = callback.get("id") if isinstance(callback, dict) else None
        if not isinstance(query_id, str):
            return
        try:
            response = self.client.post(
                _url(secrets, "answerCallbackQuery"), json={"callback_query_id": query_id}
            )
        except httpx.HTTPError as e:
            log.warning("Telegram answerCallbackQuery failed: %s", type(e).__name__)
            return
        if not response.is_success:
            log.warning("Telegram answerCallbackQuery failed: %s", _describe(response))

    # ── Outbound ──────────────────────────────────────────────────────────

    def render(self, out: Outbound, channel: Channel) -> dict[str, Any]:
        """sendMessage parameters (without chat_id), with parse_mode HTML."""
        problems = overflow(out)
        if problems:  # the common limits count code points; Telegram counts UTF-16
            log.warning("Telegram message truncated: %s", "; ".join(problems))
        header, body, buttons = _parts(out)
        if header:
            header = _cut_utf16(header, MAX_MESSAGE_UTF16 - 1)  # room for the line break
        budget = MAX_MESSAGE_UTF16 - (_utf16(header) + 1 if header else 0)
        text = _html(_cut_utf16(body, budget))
        if header:
            text = f"<b>{html.escape(header, quote=False)}</b>\n{text}"
        rendered: dict[str, Any] = {
            "text": text,
            "parse_mode": "HTML",
            "link_preview_options": NO_PREVIEW,
        }
        if buttons:
            rendered["reply_markup"] = {
                "inline_keyboard": [
                    [{"text": b.title[:MAX_BUTTON_TEXT], "callback_data": b.id}] for b in buttons
                ]
            }
        return rendered

    def send(
        self,
        rendered: dict[str, Any],
        recipient: str,
        channel: Channel,
        secrets: TelegramSecrets,
        outbound_id: UUID,
    ) -> SendOutcome:
        """`recipient` is the chat id (the user's id, in a private chat)."""
        try:
            response = self.client.post(
                _url(secrets, "sendMessage"), json={**rendered, "chat_id": recipient}
            )
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout) as e:
            log.warning("Telegram send not connected: %s", type(e).__name__)
            return RetryLater()
        except httpx.HTTPError as e:  # never str(e): it may carry the URL with the token
            log.warning("Telegram send ambiguous: %s", type(e).__name__)
            return Ambiguous(type(e).__name__)
        outcome = classify(response)
        if not isinstance(outcome, Sent):
            log.warning("Telegram send %s: %s", type(outcome).__name__, _describe(response))
        return outcome


class TelegramApiError(Exception):
    """A Bot API call other than sendMessage failed: status and error code only."""

    def __init__(self, status: int, error_code: object) -> None:
        super().__init__(f"HTTP {status}, error {error_code}")
        self.status = status


def call(
    client: httpx.Client,
    secrets: TelegramSecrets,
    method: str,
    params: dict[str, Any],
    timeout_s: float = TIMEOUT_S,
) -> Any:
    """A Bot API method (getUpdates, setWebhook…) for the operation commands: its
    `result`, or `TelegramApiError`. Never logs nor raises the URL (it holds the token)."""
    try:
        response = client.post(_url(secrets, method), json=params, timeout=timeout_s)
    except httpx.HTTPError as e:
        raise TelegramApiError(0, type(e).__name__) from None
    data = _json(response)
    if not response.is_success or data.get("ok") is not True:
        raise TelegramApiError(response.status_code, data.get("error_code"))
    return data.get("result")


def classify(response: httpx.Response) -> SendOutcome:
    """Telegram's answer → `SendOutcome`."""
    status = response.status_code
    data = _json(response)
    reason = _describe(response)
    if 200 <= status < 300:
        result = data.get("result") if data.get("ok") is True else None
        message_id = result.get("message_id") if isinstance(result, dict) else None
        if message_id is None:
            return Ambiguous("2xx without a message_id")
        return Sent(str(message_id))
    if status == 401:
        return Rejected(reason, "auth")
    if status == 403:  # the user blocked the bot
        return Rejected(reason, "recipient")
    if status == 429 or status >= 500:
        parameters = data.get("parameters")
        after = parameters.get("retry_after") if isinstance(parameters, dict) else None
        return RetryLater(_seconds(after))
    if 400 <= status < 500:
        return Rejected(reason, "other")
    return Ambiguous(reason)


def overflow(out: Outbound) -> list[str]:
    """What exceeds Telegram's own limits once rendered (the message counted in UTF-16,
    with header and list descriptions). Empty when it fits; the conversation tests fail
    otherwise."""
    header, body, buttons = _parts(out)
    size = _utf16(body) + (_utf16(header) + 1 if header else 0)
    problems = []
    if size > MAX_MESSAGE_UTF16:
        problems.append(f"message has {size} UTF-16 units (max {MAX_MESSAGE_UTF16})")
    problems += [
        f"button id has {len(b.id.encode())} bytes (max {MAX_ID_BYTES})"
        for b in buttons
        if len(b.id.encode()) > MAX_ID_BYTES
    ]
    return problems


# ── Helpers ───────────────────────────────────────────────────────────────


def _url(secrets: TelegramSecrets, method: str) -> str:
    return f"{API_URL}/bot{secrets.bot_token.get_secret_value()}/{method}"


def _private(chat: object, sender: object) -> bool:
    return (
        isinstance(chat, dict)
        and chat.get("type") == "private"
        and isinstance(sender, dict)
        and isinstance(sender.get("id"), int)
        and not sender.get("is_bot", False)
    )


def _message(message: dict[str, Any]) -> IncomingMessage | None:
    date = message.get("date")
    if not isinstance(date, int):
        return None
    received_at = datetime.fromtimestamp(date, UTC)
    text = message.get("text")
    if not isinstance(text, str):  # sticker, photo, voice, location…
        return IncomingMessage("unsupported", None, None, received_at)
    if not text.strip():
        return None
    return IncomingMessage("text", text.strip()[:MAX_TEXT], None, received_at)


def _callback(callback: dict[str, Any]) -> IncomingMessage | None:
    data = callback.get("data")
    if not isinstance(data, str) or not data or len(data.encode()) > MAX_ID_BYTES:
        return None
    # A callback carries no date of its own: the time it is parsed (the runtime keeps the
    # inbound_event's received_at).
    return IncomingMessage("button", None, data, datetime.now(UTC))


def _parts(out: Outbound) -> tuple[str | None, str, list[Button]]:
    """Header (bold first line), body and buttons. Footers are dropped; list rows become
    one button each, with their descriptions added to the body as `title: description`
    (Telegram buttons have no description)."""
    match out:
        case Text():
            return None, out.body, []
        case Buttons():
            return out.header, out.body, out.buttons
        case List():
            buttons = []
            extras = []
            for row in (r for s in out.sections for r in s.rows):
                if not row.description:
                    buttons.append(Button(row.id, row.title))
                elif row.description.startswith(row.title):
                    buttons.append(Button(row.id, row.description))
                else:
                    buttons.append(Button(row.id, row.title))
                    extras.append(f"{row.title}: {row.description}")
            body = "\n\n".join([out.body, "\n".join(extras)]) if extras else out.body
            return out.header, body, buttons
        case ProactiveMessage():
            text = _fill(out.template.text, out.params)
            titles = out.template.buttons
            return (
                None,
                text,
                [Button(p, t) for p, t in zip(out.button_payloads, titles, strict=False)],
            )


def _fill(text: str, params: list[str]) -> str:
    """Put the parameters in `{1}`, `{2}`… in one pass: a parameter that contains `{2}`
    (e.g. a contact's name) is never filled in again."""

    def param(match: re.Match[str]) -> str:
        n = int(match[1])
        return params[n - 1] if 0 < n <= len(params) else match[0]

    return PARAM.sub(param, text)


def _html(text: str) -> str:
    """Escape for parse_mode HTML and turn WhatsApp's `*bold*` into `<b>bold</b>`."""
    return BOLD.sub(r"<b>\1</b>", html.escape(text, quote=False))


def _utf16(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2


def _cut_utf16(text: str, limit: int) -> str:
    """At most `limit` UTF-16 units, never splitting a character."""
    if _utf16(text) <= limit:
        return text
    size = 0
    for i, char in enumerate(text):
        size += 2 if ord(char) > 0xFFFF else 1
        if size > limit:
            return text[:i]
    return text


def _json(response: httpx.Response) -> dict[str, Any]:
    try:
        data = response.json()
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _describe(response: httpx.Response) -> str:
    """Status and error code only: never the description nor the URL."""
    code = _json(response).get("error_code")
    return f"HTTP {response.status_code}" + (f", error {code}" if code is not None else "")


def _seconds(value: object) -> float | None:
    if not isinstance(value, int | float) or isinstance(value, bool):
        return None
    seconds = float(value)
    if not math.isfinite(seconds) or seconds < 0:
        return None
    return min(seconds, MAX_RETRY_AFTER_S)
