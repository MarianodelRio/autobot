"""Conversation rules shared by the runtime and the test harness.

Pure functions: the runtime and the harness call them in the same order,
so a scenario runs the pack exactly as production does.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Literal

from core.actions import UpdateContact
from core.messages import IncomingMessage
from core.pack import PackResult
from core.replies import Reply, Text
from core.text import normalize

RESTART_TEXT = "Perdona, he tenido que empezar de nuevo."
RECOVERY_TEXT = (
    "Uy, ha habido un problema de conexión y puede que tu última acción no se completara. "
    "Escríbeme de nuevo y seguimos."
)
OPT_OUT_TEXT = (
    "Hecho: ya no te enviaré avisos ni recordatorios. Si quieres volver a recibirlos, "
    "escribe *alta*."
)
OPT_IN_TEXT = "Hecho: volverás a recibir avisos y recordatorios."

type GlobalCommand = Literal["menu", "opt_out", "opt_in"]

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


def global_command(message: IncomingMessage) -> GlobalCommand | None:
    """Commands the runtime resolves before the pack, on the normalized text:
    `menu`, `menú`, `inicio` and `/start` → menu; `baja` → opt_out; `alta` → opt_in.
    The effective state's notices are sent with any command too."""
    if message.type != "text" or message.text is None:
        return None
    words = message.text.split()
    if words and words[0].split("@")[0].lower() == "/start":  # also "/start ref", "/start@bot"
        return "menu"
    text = normalize(message.text)
    if text in _MENU_WORDS:
        return "menu"
    if text == "baja":
        return "opt_out"
    if text == "alta":
        return "opt_in"
    return None


def menu_message(received_at: datetime) -> IncomingMessage:
    """What the pack receives, with state `{}`, after the `menu` command."""
    return IncomingMessage("text", "", None, received_at)


def opt_result(command: Literal["opt_out", "opt_in"]) -> PackResult:
    """Result of `baja` / `alta`: the contact's flag and a confirmation. `state=None`
    keeps the *effective* state (already reset if it expired), so the conversation can go
    on."""
    opt_out = command == "opt_out"
    text = OPT_OUT_TEXT if opt_out else OPT_IN_TEXT
    return PackResult(replies=[Text(text)], actions=[UpdateContact(opt_out=opt_out)])


def recovery_result() -> PackResult:
    """After an unexpected error or the last failed retry: apologise and reset."""
    return PackResult(replies=[Text(RECOVERY_TEXT)], state={})
