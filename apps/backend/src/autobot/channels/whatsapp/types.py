"""The parts of Meta's webhook the adapter reads. Bodies come from the network: every
field is checked at runtime before it is trusted; these types only say what is looked
at."""

from typing import Any, TypedDict


class TextBody(TypedDict, total=False):
    body: str


class WaMessage(TypedDict, total=False):
    id: str
    timestamp: str
    type: str
    text: TextBody
    interactive: dict[str, Any]
    button: dict[str, Any]
    user_id: str
    from_user_id: str


class WaStatus(TypedDict, total=False):
    id: str
    status: str
    biz_opaque_callback_data: str
    pricing: dict[str, Any]
    errors: list[dict[str, Any]]


class Contact(TypedDict, total=False):
    wa_id: str
    user_id: str
    profile: dict[str, Any]
