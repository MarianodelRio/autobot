"""What a menu option of the notify bot is, shared by the owner's menu (`owner.menu`)
and the operator's (`owner.operator`), so both are declarative lists of the same thing
(ADR-007, ADR-029)."""

from collections.abc import Callable
from dataclasses import dataclass

from autobot.tenancy.registry import LoadedTenant


@dataclass(frozen=True)
class OwnerChat:
    chat_id: int
    tenants: list[LoadedTenant]  # usable tenants of this chat, sorted by name
    operator: bool = False  # the operator's chat (OPS_TELEGRAM_CHAT_ID)


@dataclass(frozen=True)
class MenuOption:
    id: str  # button payload, "owner:<name>" or "ops:<name>", <= 64 bytes
    title: str  # <= 20 characters (MAX_BUTTON_TITLE)
    answer: Callable[[OwnerChat], str]
    available: Callable[[OwnerChat], bool] = lambda chat: True
