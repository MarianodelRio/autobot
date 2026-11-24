"""The notify bot's menu: declarative lists, so a future option is one entry. `MENU`
holds the owner's options (ADR-007: "Cómo va el mes", "Contacto", "Mi enlace") and
`operator.OPERATOR_MENU` the operator's (ADR-029); a chat sees the operator's ones if it
is the operator's chat, then the owner's ones if it is connected to a business."""

from datetime import datetime

from django.conf import settings
from django.utils import timezone

from autobot.owner import texts
from autobot.owner.invites import InviteError, create_invite_link
from autobot.owner.links import OWNER_INVITE_HOURS
from autobot.owner.operator import OPERATOR_MENU
from autobot.owner.options import MenuOption, OwnerChat
from autobot.runtime import summary
from autobot.tenancy.registry import LoadedTenant
from core.limits import MAX_BUTTONS, MAX_INTERACTIVE_BODY
from core.replies import Reply, Text
from core.ui import button, buttons_msg, list_msg, row, section

__all__ = ["MENU", "MenuOption", "OwnerChat", "answer", "menu_replies", "options"]


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
    return tenant.document.status == "active" and not tenant.is_degraded


def reconnect_text(chat: OwnerChat) -> str:
    """A fresh invite link per tenant of this chat, so the owner can connect
    a replacement device themselves without asking the operator. Reuses the same
    `create_invite_link` the panel's «Invitar al dueño» and `owner_invite` use."""

    lines = []
    for tenant in sorted(chat.tenants, key=lambda t: t.info.name):
        try:
            invite = create_invite_link(tenant)
        except InviteError:
            lines.append(texts.reconnect_failed(tenant))
            continue
        lines.append(
            texts.reconnect_line(
                tenant,
                invite.url,
                hours=OWNER_INVITE_HOURS,
                replaces_chat=invite.replaces_chat,
            )
        )
    return "🔗 Enlace para conectar otro dispositivo:\n\n" + "\n\n".join(lines)


MENU: list[MenuOption] = [
    MenuOption("owner:status", "📊 Cómo va el mes", status_text),
    MenuOption(
        "owner:contact",
        "✉️ Contacto",
        lambda chat: texts.contact(),
        available=lambda chat: bool(settings.OWNER_SUPPORT_EMAIL),
    ),
    MenuOption("owner:reconnect", "🔗 Mi enlace", reconnect_text),
]


def options(chat: OwnerChat) -> list[MenuOption]:
    """The options this chat sees: the operator's first (only in the operator's chat),
    then the owner's (only with a business connected)."""
    groups = ((OPERATOR_MENU, chat.operator), (MENU, bool(chat.tenants)))
    return [o for group, shown in groups if shown for o in group if o.available(chat)]


def menu_reply(chat: OwnerChat, body: str) -> Reply:
    """`body` with the available options attached: buttons for 3 or fewer, a list
    for 4 to 10 (the common limits, `core.limits`)."""
    available = options(chat)
    if len(available) <= MAX_BUTTONS:
        return buttons_msg(body, [button(o.id, o.title) for o in available])
    rows = [row(o.id, o.title) for o in available]
    return list_msg(body, "Ver opciones", [section(None, rows)])


def menu_replies(chat: OwnerChat, body: str) -> list[Reply]:
    """The answer and the menu. The operator's answers can outgrow an interactive body
    (1.024 characters): then the answer goes as a text of its own (up to 4.096) and the
    menu after it."""
    if chat.operator and len(body) > MAX_INTERACTIVE_BODY:
        return [Text(body), menu_reply(chat, texts.MORE)]
    return [menu_reply(chat, body)]


def answer(chat: OwnerChat, payload: str) -> str | None:
    """The text of the option `payload` names, or `None` if it does not match any
    option this chat sees."""
    for option in options(chat):
        if option.id == payload:
            return option.answer(chat)
    return None
