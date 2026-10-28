"""Channel adapter contract.

An adapter verifies a provider's webhook, turns its body into `ParsedItem`s, renders the
common replies into the provider's format and sends them. Packs and the runtime never
see the provider's format: the differences between channels live only in the adapters.
"""

from dataclasses import dataclass
from typing import Any, Literal, Protocol
from uuid import UUID

from django.http import HttpRequest

from core.messages import IncomingMessage
from core.serialization import Outbound

type ChannelType = Literal["whatsapp", "telegram"]


@dataclass(frozen=True)
class InboundItem:
    """A message from a contact."""

    provider_event_id: str  # unique per channel: the inbound_event's idempotency key
    external_id: str  # BSUID or phone (WhatsApp), user id (Telegram)
    display_name: str | None
    phone: str | None  # E.164 with "+", only when the provider gives it
    message: IncomingMessage
    # The item on its own, in the provider's format, as stored in inbound_event.payload:
    # `parse(payload)` gives back this item (see `parse_stored`); only a Telegram
    # callback_query, which has no date, gets the time of the new parse as received_at.
    payload: dict[str, Any]


@dataclass(frozen=True)
class StatusItem:
    """A delivery status of a message we sent (WhatsApp only)."""

    provider_event_id: str
    outbound_ref: str | None  # our outbound_message id, echoed back by the provider
    provider_message_id: str
    status: Literal["sent", "delivered", "read", "failed"]
    pricing_category: str | None
    billable: bool | None
    error: str | None  # provider error codes of a `failed` status, never their text
    payload: dict[str, Any]


type ParsedItem = InboundItem | StatusItem


@dataclass(frozen=True)
class Sent:
    provider_message_id: str


@dataclass(frozen=True)
class Rejected:
    """The provider refused the message: resending it as is would fail again.
    `reason` holds status and error codes only, never the response body."""

    reason: str
    kind: Literal["auth", "recipient", "other"]


@dataclass(frozen=True)
class RetryLater:
    """Certainly not sent; may be retried (after `after_s` seconds, if the provider says)."""

    after_s: float | None = None


@dataclass(frozen=True)
class Ambiguous:
    """It may or may not have been sent: never resent blindly."""

    reason: str


type SendOutcome = Sent | Rejected | RetryLater | Ambiguous


class ChannelAdapter[C, S](Protocol):
    """`C` is the channel's description (its tenant.yaml `channel`, or the test bot) and
    `S` its secrets."""

    @property
    def type(self) -> ChannelType: ...

    def verify(self, request: HttpRequest, channel: C, secrets: S) -> bool:
        """Is the request authentic? Checked before anything else, in constant time."""
        ...

    def parse(self, body: dict[str, Any], channel: C) -> list[ParsedItem]:
        """The items of a webhook body; anything malformed or foreign is dropped."""
        ...

    def acknowledge(self, payload: dict[str, Any], channel: C, secrets: S) -> None:
        """Immediate effects once an item is taken (Telegram: answerCallbackQuery)."""
        ...

    def render(self, out: Outbound, channel: C) -> dict[str, Any]:
        """The provider's request body for a reply or proactive message (no recipient)."""
        ...

    def send(
        self, rendered: dict[str, Any], recipient: str, channel: C, secrets: S, outbound_id: UUID
    ) -> SendOutcome: ...


def parse_stored[C](
    adapter: ChannelAdapter[C, Any], payload: dict[str, Any], channel: C
) -> ParsedItem:
    """The item stored in an inbound_event.payload."""
    items = adapter.parse(payload, channel)
    if len(items) != 1:
        raise ValueError(f"a stored payload must hold one item, not {len(items)}")
    return items[0]
