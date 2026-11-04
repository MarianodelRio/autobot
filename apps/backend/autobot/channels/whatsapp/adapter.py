"""WhatsApp Cloud API adapter.

Logs never carry identifiers, texts or provider response bodies (a 4xx body may hold
personal data): only status and error codes.
"""

import hashlib
import hmac
import logging
import math
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

import httpx
from django.conf import settings
from django.http import HttpRequest

from autobot.channels.base import (
    Ambiguous,
    InboundItem,
    ParsedItem,
    Rejected,
    RetryLater,
    SendOutcome,
    Sent,
    StatusItem,
)
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
MAX_RETRY_AFTER_S = 3600.0

STATUSES = frozenset({"sent", "delivered", "read", "failed"})
# Graph API error codes. 190: invalid or expired access token. Recipient that cannot
# receive: 131021 (recipient is the sender), 131026 (undeliverable: no WhatsApp, old
# version…), 131030 (not in the allowed list of a test number).
AUTH_ERROR = 190
RECIPIENT_ERRORS = frozenset({131021, 131026, 131030})
# Message types that do not come from the contact (e.g. a number change): never answered.
IGNORED_TYPES = frozenset({"system"})


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
                contacts = _dicts(value.get("contacts"))
                for message in _dicts(value.get("messages")):
                    item = _message(entry, value, message, contacts)
                    if item is not None:
                        items.append(item)
                for status in _dicts(value.get("statuses")):
                    status_item = _status(entry, value, status)
                    if status_item is not None:
                        items.append(status_item)
        return items

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
            return RetryLater()
        except httpx.HTTPError as e:  # timeout or network error after connecting
            log.warning("WhatsApp send ambiguous: %s", type(e).__name__)
            return Ambiguous(type(e).__name__)
        outcome = classify(response)
        if not isinstance(outcome, Sent):
            log.warning("WhatsApp send %s: %s", type(outcome).__name__, _describe(response))
        return outcome


def classify(response: httpx.Response) -> SendOutcome:
    """Meta's answer → `SendOutcome`."""
    status = response.status_code
    error = _error(response)
    reason = _describe(response)
    if 200 <= status < 300:
        try:
            data = response.json()
            return Sent(str(data["messages"][0]["id"]))
        except ValueError, LookupError, TypeError:
            return Ambiguous("2xx without a message id")
    code = error.get("code") if error is not None else None
    if status == 401 or code == AUTH_ERROR:
        return Rejected(reason, "auth")
    if status == 429:
        return RetryLater(_retry_after(response))
    if status == 400 and code in RECIPIENT_ERRORS:
        return Rejected(reason, "recipient")
    if 400 <= status < 500:
        return Rejected(reason, "other")
    if status >= 500 and error is not None:  # Meta answered with an error: not sent
        return RetryLater(_retry_after(response))
    return Ambiguous(reason)  # e.g. 502/504 from a proxy, without Meta's error body


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


def _timestamp(value: object) -> datetime | None:
    try:
        return datetime.fromtimestamp(int(str(value)), UTC)
    except ValueError, OverflowError, OSError:
        return None


def _message(
    entry: dict[str, Any],
    value: dict[str, Any],
    message: dict[str, Any],
    contacts: list[dict[str, Any]],
) -> InboundItem | None:
    wamid = message.get("id")
    received_at = _timestamp(message.get("timestamp"))
    if not isinstance(wamid, str) or not 0 < len(wamid) <= MAX_EVENT_ID or received_at is None:
        log.warning("WhatsApp message without a valid id or timestamp dropped")
        return None
    phone = message.get("from")
    phone = phone if isinstance(phone, str) and PHONE.match(phone) else None
    # The BSUID (since April 2026) identifies the contact even when the phone is hidden.
    bsuid = message.get("from_user_id") or message.get("user_id")
    external_id = bsuid if isinstance(bsuid, str) and BSUID.match(bsuid) else phone
    if external_id is None:
        log.warning("WhatsApp message without a valid sender dropped")
        return None
    kind = message.get("type")
    if kind in IGNORED_TYPES:
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
        payload=_single(entry, value, "messages", message, **extra),
    )


def _incoming(message: dict[str, Any], received_at: datetime) -> IncomingMessage | None:
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


def _status(
    entry: dict[str, Any], value: dict[str, Any], status: dict[str, Any]
) -> StatusItem | None:
    wamid = status.get("id")
    name = status.get("status")
    if not isinstance(wamid, str) or not wamid or name not in STATUSES:
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
        status=name,
        pricing_category=category[:32] if isinstance(category, str) else None,
        billable=billable if isinstance(billable, bool) else None,
        error=",".join(codes) or None,
        payload=_single(entry, value, "statuses", status),
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
    try:
        data = response.json()
    except ValueError:
        return None
    error = data.get("error") if isinstance(data, dict) else None
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
    if not math.isfinite(seconds) or seconds < 0:
        return None
    return min(seconds, MAX_RETRY_AFTER_S)
