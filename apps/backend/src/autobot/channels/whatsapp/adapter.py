"""WhatsApp Cloud API adapter.

Logs never carry identifiers, texts or provider response bodies (a 4xx body may hold
personal data): only status and error codes.
"""

import copy
import hashlib
import hmac
import logging
import re
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, cast
from uuid import UUID

import httpx
from django.conf import settings
from django.http import HttpRequest

from autobot.channels.base import (
    Ambiguous,
    ErrorClass,
    InboundItem,
    ParsedItem,
    Rejected,
    RetryLater,
    SendOutcome,
    Sent,
    StatusItem,
)
from autobot.channels.http_outcome import clamp_retry_after, safe_json_dict
from autobot.channels.payload import clean_payload
from autobot.channels.whatsapp.types import Contact, WaMessage, WaStatus
from autobot.tenancy.schema import BSUID, PHONE, WhatsAppChannel, WhatsAppSecrets
from core.limits import MAX_ID_BYTES, MAX_TEXT
from core.messages import IncomingMessage
from core.proactive import ProactiveMessage
from core.replies import Buttons, List, Text
from core.serialization import Outbound

log = logging.getLogger(__name__)

GRAPH_URL = "https://graph.facebook.com"
TIMEOUT_S = 10.0
SIGNATURE_HEADER = "X-Hub-Signature-256"
MAX_EVENT_ID = 200  # inbound_event.provider_event_id

STATUSES = frozenset({"sent", "delivered", "read", "failed"})
# Graph API error codes of a send, and what each becomes (`classify`):
#
# - 190: invalid or expired access token -> Rejected(auth).
# - 131021 (recipient is the sender), 131026 (undeliverable: no WhatsApp, old version…),
#   131030 (not in the allowed list of a test number) -> Rejected(recipient).
# - Rate limits, with HTTP 4xx (Meta does not always use 429) -> RetryLater, backed off by
#   the job: nothing was sent and the limit lifts by itself.
#     4 (app: too many calls), 17 (user: too many calls), 32 (page: too many calls),
#     613 (too many calls to this API), 80007 (WhatsApp Business Management API),
#     130429 (Cloud API throughput reached), 131056 (too many messages to the same
#     contact: pair rate limit).
# - Anything else with HTTP 4xx -> Rejected(other), notably 131047 (outside the 24 h
#   window: needs a template) and 131049 (Meta chose not to deliver a marketing message):
#   retrying the same message never helps. 131048 (spam rate limit) is not retried either:
#   insisting makes the quality rating worse.
AUTH_ERROR = 190
RECIPIENT_ERRORS = frozenset({131021, 131026, 131030})
RATE_LIMIT_ERRORS = frozenset({4, 17, 32, 613, 80007, 130429, 131056})
OUTSIDE_WINDOW_ERROR = 131047
SPAM_LIMIT_ERROR = 131048
MARKETING_DECLINED_ERROR = 131049
# The two formats `last_error` holds: a synchronous rejection ("HTTP 400, error 131047[/sub]",
# `_describe`) and an asynchronous `failed` status ("status failed: 131047,…", runtime).
_SYNC_ERROR = re.compile(r"HTTP (\d{3})(?:, error (\d+))?")
_ASYNC_ERROR = re.compile(r"status failed: ([\d,]+)")
# Message types that are not the contact writing to the business, never answered: a
# system notice (e.g. a number change), a reaction to a message, the `request_welcome`
# of a chat opened from an ad or a "click to chat" button. Media (audio, image…) is not
# here: the contact did write, and the pack answers that it cannot read it.
IGNORED_TYPES = frozenset({"system", "reaction", "request_welcome"})


class WhatsAppAdapter:
    type: Literal["whatsapp"] = "whatsapp"

    def __init__(self, client: httpx.Client | None = None) -> None:
        # One pooled client per process; tests inject one with a mock transport.
        self.client = client or httpx.Client(timeout=TIMEOUT_S)

    # ── Inbound ───────────────────────────────────────────────────────────

    def verify(
        self, request: HttpRequest, channel: WhatsAppChannel, secrets: WhatsAppSecrets
    ) -> bool:
        """`X-Hub-Signature-256` = HMAC-SHA256 of the raw body with the app secret."""
        header = request.headers.get(SIGNATURE_HEADER, "")
        if not header.startswith("sha256="):
            return False
        expected = hmac.new(
            secrets.app_secret.get_secret_value().encode(), request.body, hashlib.sha256
        ).hexdigest()
        # As bytes: compare_digest raises on non-ASCII str (headers are decoded as latin-1).
        return hmac.compare_digest(expected.encode(), header.removeprefix("sha256=").encode())

    def verify_subscription(self, params: dict[str, str], secrets: WhatsAppSecrets) -> str | None:
        """Meta's `GET` handshake: the challenge to echo back, or None to refuse."""
        token = params.get("hub.verify_token", "")
        expected = secrets.verify_token.get_secret_value()
        if params.get("hub.mode") != "subscribe" or not hmac.compare_digest(
            token.encode(), expected.encode()
        ):
            return None
        return params.get("hub.challenge", "")

    def parse(self, body: dict[str, Any], channel: WhatsAppChannel) -> list[ParsedItem]:
        body = clean_payload(body)  # what is stored must be accepted by jsonb
        items: list[ParsedItem] = []
        for entry in _dicts(body.get("entry")):
            for change in _dicts(entry.get("changes")):
                value = change.get("value")
                if change.get("field", "messages") != "messages" or not isinstance(value, dict):
                    continue
                metadata = value.get("metadata")
                number = metadata.get("phone_number_id") if isinstance(metadata, dict) else None
                if number is None or number != channel.phone_number_id:
                    log.warning("WhatsApp change for another phone_number_id dropped")
                    continue
                contacts = cast(list[Contact], _dicts(value.get("contacts")))
                for message in _dicts(value.get("messages")):
                    item = _message(entry, value, cast(WaMessage, message), contacts)
                    if item is not None:
                        items.append(item)
                for status in _dicts(value.get("statuses")):
                    status_item = _status(entry, value, cast(WaStatus, status))
                    if status_item is not None:
                        items.append(status_item)
        return items

    def synthetic_text(self, payload: dict[str, Any], text: str) -> dict[str, Any]:
        body = copy.deepcopy(payload)
        message = body["entry"][0]["changes"][0]["value"]["messages"][0]
        kept = {
            k: message[k]
            for k in ("from", "from_user_id", "user_id", "id", "timestamp")
            if k in message
        }
        message.clear()
        message.update(kept)
        message["type"] = "text"
        message["text"] = {"body": text}
        return body

    def acknowledge(
        self, payload: dict[str, Any], channel: WhatsAppChannel, secrets: WhatsAppSecrets
    ) -> None:
        """Nothing to acknowledge in WhatsApp."""

    # ── Outbound ──────────────────────────────────────────────────────────

    def render(self, out: Outbound, channel: WhatsAppChannel) -> dict[str, Any]:
        match out:
            case Text():
                return {"type": "text", "text": {"body": out.body, "preview_url": False}}
            case Buttons():
                buttons = [
                    {"type": "reply", "reply": {"id": b.id, "title": b.title}} for b in out.buttons
                ]
                return _interactive(
                    "button", out.body, {"buttons": buttons}, out.header, out.footer
                )
            case List():
                sections = [
                    {
                        **({"title": s.title} if s.title else {}),
                        "rows": [
                            {
                                "id": r.id,
                                "title": r.title,
                                **({"description": r.description} if r.description else {}),
                            }
                            for r in s.rows
                        ],
                    }
                    for s in out.sections
                ]
                action = {"button": out.button_label, "sections": sections}
                return _interactive("list", out.body, action, out.header, out.footer)
            case ProactiveMessage():
                return {"type": "template", "template": _template(out)}

    def send(
        self,
        rendered: dict[str, Any],
        recipient: str,
        channel: WhatsAppChannel,
        secrets: WhatsAppSecrets,
        outbound_id: UUID,
    ) -> SendOutcome:
        """`recipient` is a phone (with or without "+") or a BSUID. Meta echoes
        `biz_opaque_callback_data` in the message's statuses (`StatusItem.outbound_ref`)."""
        if channel.phone_number_id is None:
            return Rejected("channel has no phone_number_id", "other")
        phone = recipient.removeprefix("+")
        to = {"to": phone} if PHONE.match(phone) else {"recipient": recipient}
        body = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            **to,
            **rendered,
            "biz_opaque_callback_data": str(outbound_id),
        }
        url = f"{GRAPH_URL}/{settings.WHATSAPP_GRAPH_VERSION}/{channel.phone_number_id}/messages"
        headers = {"Authorization": f"Bearer {secrets.access_token.get_secret_value()}"}
        try:
            response = self.client.post(url, json=body, headers=headers)
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout) as e:
            # No connection was made (or none was free in the pool): nothing was sent.
            log.warning("WhatsApp send not connected: %s", type(e).__name__)
            return RetryLater(kind="network")
        except httpx.HTTPError as e:  # timeout or network error after connecting
            log.warning("WhatsApp send ambiguous: %s", type(e).__name__)
            return Ambiguous(type(e).__name__, transport=True)
        outcome = classify(response)
        if not isinstance(outcome, Sent):
            log.warning("WhatsApp send %s: %s", type(outcome).__name__, _describe(response))
        return outcome

    def probe(self, channel: WhatsAppChannel, secrets: WhatsAppSecrets) -> bool:
        """GET of the phone-number node: sends nothing."""
        if channel.phone_number_id is None:
            return False
        url = f"{GRAPH_URL}/{settings.WHATSAPP_GRAPH_VERSION}/{channel.phone_number_id}"
        headers = {"Authorization": f"Bearer {secrets.access_token.get_secret_value()}"}
        try:
            response = self.client.get(url, params={"fields": "id"}, headers=headers)
        except httpx.HTTPError as e:
            log.warning("WhatsApp probe failed: %s", type(e).__name__)
            return False
        return response.status_code < 500


def classify(response: httpx.Response) -> SendOutcome:
    """Meta's answer → `SendOutcome`."""
    status = response.status_code
    error = _error(response)
    reason = _describe(response)
    if 200 <= status < 300:
        try:
            return Sent(str(safe_json_dict(response)["messages"][0]["id"]))
        except LookupError, TypeError:
            return Ambiguous("2xx without a message id")
    code = error.get("code") if error is not None else None
    if status == 401 or code == AUTH_ERROR:
        return Rejected(reason, "auth")
    if status == 429 or (400 <= status < 500 and code in RATE_LIMIT_ERRORS):
        return RetryLater(_retry_after(response), "rate")
    if status == 400 and code in RECIPIENT_ERRORS:
        return Rejected(reason, "recipient")
    if 400 <= status < 500:
        return Rejected(reason, "other")
    if status >= 500 and error is not None:  # Meta answered with an error: not sent
        return RetryLater(_retry_after(response), "server")
    return Ambiguous(
        reason, transport=status >= 500
    )  # e.g. 502/504 from a proxy, without Meta's error body


def _code_class(code: int) -> ErrorClass:
    if code == AUTH_ERROR:
        return "auth"
    if code == OUTSIDE_WINDOW_ERROR:
        return "outside_window"
    if code in RECIPIENT_ERRORS:
        return "undeliverable"
    if code == MARKETING_DECLINED_ERROR:
        return "marketing_declined"
    if code == SPAM_LIMIT_ERROR:
        return "spam_limit"
    if code in RATE_LIMIT_ERRORS:
        return "rate"
    return "other"


def error_class(last_error: str) -> ErrorClass:
    """The class of a stored `last_error` of a WhatsApp send (pure; reads both formats)."""
    if (match := _ASYNC_ERROR.search(last_error)) is not None:
        classes = [_code_class(int(code)) for code in match[1].split(",") if code]
        return next((c for c in classes if c != "other"), "other")
    if (match := _SYNC_ERROR.search(last_error)) is not None:
        status = int(match[1])
        if match[2] is not None:
            found = _code_class(int(match[2]))
            if found != "other":
                return found
        if status == 401:
            return "auth"
        if status == 429:
            return "rate"
    return "other"


# ── Helpers ───────────────────────────────────────────────────────────────


def _dicts(value: object) -> list[dict[str, Any]]:
    return [v for v in value if isinstance(v, dict)] if isinstance(value, list) else []


def _single(
    entry: dict[str, Any], value: dict[str, Any], key: str, element: dict[str, Any], **extra: Any
) -> dict[str, Any]:
    """A webhook body with just this element: what inbound_event.payload stores, and what
    `parse` turns back into the same item."""
    one = {"messaging_product": value.get("messaging_product"), "metadata": value["metadata"]}
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": entry.get("id"),
                "changes": [{"field": "messages", "value": {**one, **extra, key: [element]}}],
            }
        ],
    }


# Anything older is dropped at parse time: a replay of a captured webhook (the signature
# does not cover freshness) must not be accepted after the retention of the dedupe rows.
MAX_AGE = timedelta(hours=48)


def _now() -> datetime:
    return datetime.now(UTC)


def _too_old(value: object) -> bool:
    """Is `value` (a Unix timestamp as Meta sends it) older than `MAX_AGE`? An absent or
    unreadable one is not: those are judged by their own rules."""
    when = _timestamp(value)
    return when is not None and _now() - when > MAX_AGE


def _timestamp(value: object) -> datetime | None:
    try:
        return datetime.fromtimestamp(int(str(value)), UTC)
    except ValueError, OverflowError, OSError:
        return None


def _extract_sender(message: WaMessage) -> tuple[str | None, str | None]:
    """`(phone, external_id)` of whoever wrote: the phone digits if valid, and the id the
    platform knows them by (the BSUID when there is one, else the phone)."""
    phone = message.get("from")
    phone = phone if isinstance(phone, str) and PHONE.match(phone) else None
    # The BSUID (since April 2026) identifies the contact even when the phone is hidden.
    bsuid = message.get("from_user_id") or message.get("user_id")
    external_id = bsuid if isinstance(bsuid, str) and BSUID.match(bsuid) else phone
    return phone, external_id


def _message(
    entry: dict[str, Any],
    value: dict[str, Any],
    message: WaMessage,
    contacts: list[Contact],
) -> InboundItem | None:
    wamid = message.get("id")
    received_at = _timestamp(message.get("timestamp"))
    if not isinstance(wamid, str) or not 0 < len(wamid) <= MAX_EVENT_ID or received_at is None:
        log.warning("WhatsApp message without a valid id or timestamp dropped")
        return None
    if _too_old(message.get("timestamp")):
        log.warning("WhatsApp message older than %s dropped", MAX_AGE)
        return None
    phone, external_id = _extract_sender(message)
    if external_id is None:
        log.warning("WhatsApp message without a valid sender dropped")
        return None
    if message.get("type") in IGNORED_TYPES:
        return None
    incoming = _incoming(message, received_at)
    if incoming is None:
        return None

    contact = next(
        (c for c in contacts if external_id in (c.get("user_id"), c.get("wa_id"))),
        contacts[0] if len(contacts) == 1 else None,
    )
    profile = contact.get("profile") if contact else None
    name = profile.get("name") if isinstance(profile, dict) else None
    extra = {"contacts": [contact]} if contact else {}
    return InboundItem(
        provider_event_id=wamid,
        external_id=external_id,
        display_name=name[:200] if isinstance(name, str) and name else None,
        phone=f"+{phone}" if phone else None,
        message=incoming,
        payload=_single(entry, value, "messages", cast(dict[str, Any], message), **extra),
    )


def _incoming(message: WaMessage, received_at: datetime) -> IncomingMessage | None:
    kind = message.get("type")
    if kind == "text":
        text = message.get("text")
        body = text.get("body") if isinstance(text, dict) else None
        if not isinstance(body, str) or not body.strip():
            return None
        return IncomingMessage("text", body.strip()[:MAX_TEXT], None, received_at)
    payload: object = None
    if kind == "interactive":
        interactive = message.get("interactive")
        if not isinstance(interactive, dict):
            return None
        subtype = interactive.get("type")
        if subtype not in ("button_reply", "list_reply"):
            return IncomingMessage("unsupported", None, None, received_at)
        reply = interactive.get(subtype)
        payload = reply.get("id") if isinstance(reply, dict) else None
    elif kind == "button":  # a button of a template (proactive message)
        button = message.get("button")
        payload = button.get("payload") if isinstance(button, dict) else None
    else:  # audio, image, document, sticker, location, reaction…
        return IncomingMessage("unsupported", None, None, received_at)
    if not isinstance(payload, str) or not payload or len(payload.encode()) > MAX_ID_BYTES:
        log.warning("WhatsApp button without a valid id dropped")
        return None
    return IncomingMessage("button", None, payload, received_at)


def _status(entry: dict[str, Any], value: dict[str, Any], status: WaStatus) -> StatusItem | None:
    wamid = status.get("id")
    name = status.get("status")
    if not isinstance(wamid, str) or not wamid or name not in STATUSES:
        return None
    if _too_old(status.get("timestamp")):
        log.warning("WhatsApp status older than %s dropped", MAX_AGE)
        return None
    event_id = f"{wamid}:{name}"
    if len(event_id) > MAX_EVENT_ID:
        log.warning("WhatsApp status with an overlong id dropped")
        return None
    pricing = status.get("pricing")
    pricing = pricing if isinstance(pricing, dict) else {}
    category = pricing.get("category")
    billable = pricing.get("billable")
    ref = status.get("biz_opaque_callback_data")
    codes = [str(e.get("code")) for e in _dicts(status.get("errors")) if e.get("code") is not None]
    return StatusItem(
        provider_event_id=event_id,
        outbound_ref=ref if isinstance(ref, str) and ref else None,
        provider_message_id=wamid,
        status=cast(Literal["sent", "delivered", "read", "failed"], name),
        pricing_category=category[:32] if isinstance(category, str) else None,
        billable=billable if isinstance(billable, bool) else None,
        error=",".join(codes) or None,
        payload=_single(entry, value, "statuses", cast(dict[str, Any], status)),
    )


def _interactive(
    kind: str, body: str, action: dict[str, Any], header: str | None, footer: str | None
) -> dict[str, Any]:
    interactive: dict[str, Any] = {"type": kind, "body": {"text": body}, "action": action}
    if header:
        interactive["header"] = {"type": "text", "text": header}
    if footer:
        interactive["footer"] = {"text": footer}
    return {"type": "interactive", "interactive": interactive}


def _template(out: ProactiveMessage) -> dict[str, Any]:
    components: list[dict[str, Any]] = []
    if out.params:
        components.append(
            {"type": "body", "parameters": [{"type": "text", "text": p} for p in out.params]}
        )
    for index, payload in enumerate(out.button_payloads):
        components.append(
            {
                "type": "button",
                "sub_type": "quick_reply",
                "index": str(index),
                "parameters": [{"type": "payload", "payload": payload}],
            }
        )
    return {
        "name": out.template.name,
        "language": {"code": out.template.language},
        "components": components,
    }


def _error(response: httpx.Response) -> dict[str, Any] | None:
    """Meta's error object, if the body is one (`{"error": {"code": …}}`)."""
    error = safe_json_dict(response).get("error")
    return error if isinstance(error, dict) else None


def _describe(response: httpx.Response) -> str:
    """Status and error codes only: the body may hold personal data."""
    error = _error(response)
    if error is None:
        return f"HTTP {response.status_code}"
    codes = [str(error[k]) for k in ("code", "error_subcode") if error.get(k) is not None]
    return f"HTTP {response.status_code}, error {'/'.join(codes) or '?'}"


def _retry_after(response: httpx.Response) -> float | None:
    try:
        seconds = float(response.headers.get("retry-after", ""))
    except ValueError:
        return None
    return clamp_retry_after(seconds)
