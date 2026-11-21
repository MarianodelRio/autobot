"""The parts of Telegram's Bot API update the adapter reads. Bodies come from the
network: every field is checked at runtime before it is trusted; these types only say
what is looked at."""

from typing import TypedDict


class User(TypedDict, total=False):
    id: int
    is_bot: bool
    first_name: str


class Chat(TypedDict, total=False):
    id: int
    type: str


Message = TypedDict(
    "Message",
    {"message_id": int, "date": int, "text": str, "chat": Chat, "from": User},
    total=False,
)  # functional form: `from` is a keyword


Callback = TypedDict(
    "Callback",
    {"id": str, "data": str, "message": Message, "from": User},
    total=False,
)
