"""Conversation rules shared by the runtime and the test harness.

Pure functions: the runtime and the harness call them in the same order,
so a scenario runs the pack exactly as production does.
"""

import dataclasses
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Literal

from core.limits import MAX_INTERACTIVE_BODY, MAX_TEXT, SEPARATOR
from core.messages import IncomingMessage
from core.pack import PackResult, TenantInfo
from core.replies import Reply, Text
from core.text import normalize

RESTART_TEXT = "Perdona, he tenido que empezar de nuevo."
RECOVERY_TEXT = (
    "Uy, ha habido un problema de conexión y puede que tu última acción no se completara. "
    "Escríbeme de nuevo y seguimos."
)
# The last attempt of a message failed on a temporary error of something outside the
# platform: the person is told, and the conversation stays where it was so they can repeat.
DEGRADED_TEXT = "Ahora mismo no puedo completar tu consulta. Prueba de nuevo en unos minutos."
# Sent once (at most one per contact every 6 hours) in place of a reply that could not be
# delivered in time, which is dropped: its buttons may be obsolete (ADR-024).
APOLOGY_TEXT = (
    "Perdona el retraso, hemos tenido un problema técnico. ¿Seguimos? Escribe *menú* para empezar."
)
_MENU_WORDS = frozenset({"menu", "inicio"})  # normalized: "menú" → "menu"


@dataclass(frozen=True)
class EffectiveState:
    state: dict[str, Any]
    reset: Literal["expired", "version"] | None = None
    # Replies to send before the pack's own (the friendly restart text).
    notices: list[Reply] = field(default_factory=list)


def effective_state(
    state: Mapping[str, Any],
    state_version: int | None,
    last_inbound_at: datetime | None,
    *,
    pack_state_version: int,
    timeout_min: int,
    now: datetime,
) -> EffectiveState:
    """The state the pack sees: reset to `{}` when the conversation expired (more than
    `timeout_min` since the last message, silently) or when its shape changed (another
    `state_version` after a deploy, with the friendly restart text)."""
    if not state:
        return EffectiveState({})
    if last_inbound_at is None or now - last_inbound_at > timedelta(minutes=timeout_min):
        return EffectiveState({}, "expired")  # silent: the pack just starts over
    if state_version != pack_state_version:
        return EffectiveState({}, "version", [Text(RESTART_TEXT)])
    return EffectiveState(dict(state))


def is_menu_command(message: IncomingMessage) -> bool:
    """The only command the runtime resolves before the pack, on the normalized text:
    `menu`, `menú`, `inicio` and `/start` (also `/start ref`, `/start@bot`) restart the
    conversation from the pack's menu. The effective state's notices go with it too."""
    if message.type != "text" or message.text is None:
        return False
    words = message.text.split()
    if words and words[0].split("@")[0].lower() == "/start":
        return True
    return normalize(message.text) in _MENU_WORDS


def menu_message(received_at: datetime) -> IncomingMessage:
    """What the pack receives, with state `{}`, after the `menu` command."""
    return IncomingMessage("text", "", None, received_at)


def recovery_result() -> PackResult:
    """After an unexpected error or the last failed retry: apologise and reset."""
    return PackResult(replies=[Text(RECOVERY_TEXT)], state={})


def degraded_result() -> PackResult:
    """After the last failed attempt on a temporary error: say so and keep the state
    (`state=None`: unchanged), so repeating the last action carries on from the same
    step instead of starting over."""
    return PackResult(replies=[Text(DEGRADED_TEXT)])


def first_contact_notice(tenant: TenantInfo) -> str:
    """First layer of the privacy information (RGPD art. 13), in one discreet line: that
    an automatic assistant answers and where to read the rest. Without a policy link it
    names the controller only when it is not the business itself. Added below the pack's
    menu every time it is shown (`PackResult.menu`) and below a contact's very first
    reply (`with_notice`)."""
    if tenant.policy_url:
        return f"_🤖 Asistente automático de {tenant.name} · Privacidad:_ {tenant.policy_url}"
    controller = tenant.controller_name
    if controller and normalize(controller) != normalize(tenant.name):
        return f"_🤖 Asistente automático de {tenant.name} · Responsable: {controller}_"
    return f"_🤖 Asistente automático de {tenant.name}_"  # the business is the controller


def with_notice(replies: list[Reply], notice: str) -> list[Reply]:
    """The privacy line as the last line of the last reply, after a blank line,
    so it never pushes the answer down; as a text of its own after it when it does not
    fit (or there is no reply)."""
    if replies:
        last = replies[-1]
        limit = MAX_TEXT if isinstance(last, Text) else MAX_INTERACTIVE_BODY
        body = f"{last.body}{SEPARATOR}{notice}"
        if len(body) <= limit:
            return [*replies[:-1], dataclasses.replace(last, body=body)]
    return [*replies, Text(notice)]
