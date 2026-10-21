"""What a pack receives from a contact (design.md §6.1)."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal


@dataclass(frozen=True)
class IncomingMessage:
    # button = a pressed button, list row or proactive-message button
    type: Literal["text", "button", "unsupported"]
    text: str | None
    payload: str | None  # id of the pressed button or row
    received_at: datetime
