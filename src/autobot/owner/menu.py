"""The owner bot's menu: a declarative list, so a future option is one entry
(ADR-007). "Cómo va el mes" (`status_text`) and
"Contacto" are the first two."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from django.conf import settings
from django.utils import timezone

from autobot.owner import texts
from autobot.runtime import summary
from autobot.tenancy.registry import LoadedTenant
from core.limits import MAX_BUTTONS
from core.replies import Reply
from core.ui import button, buttons_msg, list_msg, row, section


@dataclass(frozen=True)
class OwnerChat:
    chat_id: int
    tenants: list[LoadedTenant]  # usable tenants of this chat, sorted by name


@dataclass(frozen=True)
class MenuOption:
    id: str  # button payload, "owner:<name>", <= 64 bytes
    title: str  # <= 20 characters (MAX_BUTTON_TITLE)
    answer: Callable[[OwnerChat], str]
    available: Callable[[OwnerChat], bool] = lambda chat: True


def status_text(chat: OwnerChat) -> str:
    return _status_text(chat, timezone.now())


def _status_text(chat: OwnerChat, now: datetime) -> str:
    sections: list[str] = []
    any_eur = False
    head = None
    for tenant in sorted(chat.tenants, key=lambda t: t.info.name):
        start, end = summary.month_to_date(now, tenant.info.timezone)
        if head is None:
            head = summary.header(start, end, monthly=False)
        if not _usable(tenant):
            sections.append(f"{tenant.info.name}\n\n{texts.not_active(tenant)}")
            continue
        block = summary.build_summary(tenant, start, end)
        if block.pack_failed:
            sections.append(f"{tenant.info.name}\n\n{texts.PACK_FAILED}")
            continue
        sections.append(f"{tenant.info.name}\n\n" + "\n".join(summary.block_lines(block)))
        any_eur = any_eur or any(line.unit == "eur" for line in block.pack_lines)
    assert head is not None  # chat.tenants is never empty when this is called
    text = head + "\n" + "\n\n".join(sections)
    if any_eur:
        text += "\n\n" + summary.note(monthly=False)
    return text


def _usable(tenant: LoadedTenant) -> bool:
    """ADR-007: a demo tenant answers even `paused`; a real
    tenant must be `active` and not degraded."""
    if tenant.is_demo:
        return True
    return tenant.file.status == "active" and not tenant.is_degraded


MENU: list[MenuOption] = [
    MenuOption("owner:status", "📊 Cómo va el mes", status_text),
    MenuOption(
        "owner:contact",
        "✉️ Contacto",
        lambda chat: texts.contact(),
        available=lambda chat: bool(settings.OWNER_SUPPORT_EMAIL),
    ),
]


def menu_reply(chat: OwnerChat, body: str) -> Reply:
    """`body` with the available options attached: buttons for 3 or fewer, a list
    for 4 to 10 (the common limits, `core.limits`)."""
    options = [option for option in MENU if option.available(chat)]
    if len(options) <= MAX_BUTTONS:
        return buttons_msg(body, [button(o.id, o.title) for o in options])
    rows = [row(o.id, o.title) for o in options]
    return list_msg(body, "Ver opciones", [section(None, rows)])


def answer(chat: OwnerChat, payload: str) -> str | None:
    """The text of the option `payload` names, or `None` if it does not match any
    available option."""
    for option in MENU:
        if option.id == payload and option.available(chat):
            return option.answer(chat)
    return None
