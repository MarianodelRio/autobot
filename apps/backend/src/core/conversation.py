"""Conversation rules shared by the runtime and the test harness.

Pure functions: the runtime and the harness call them in the same order,
so a scenario runs the pack exactly as production does.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Literal

from core.actions import NotifyOwner, UpdateContact
from core.messages import IncomingMessage
from core.pack import ContactInfo, PackResult, TenantInfo
from core.replies import Reply, Text
from core.text import normalize
from core.ui import button, buttons_msg

RESTART_TEXT = "Perdona, he tenido que empezar de nuevo."
RECOVERY_TEXT = (
    "Uy, ha habido un problema de conexión y puede que tu última acción no se completara. "
    "Escríbeme de nuevo y seguimos."
)
OPT_OUT_TEXT = (
    "Hecho: ya no te enviaré avisos ni recordatorios (puedes seguir escribiéndome cuando "
    "quieras). Si quieres volver a recibirlos, escribe *alta*. Para que borren tus datos, "
    "contacta directamente con el negocio."
)
OPT_IN_TEXT = "Hecho: volverás a recibir avisos y recordatorios."

# The kind of `NotifyOwner` sent when a contact asks for a person. The platform always
# delivers it (it ignores `owner.notify`): it is a customer-service obligation, not an
# optional notice, and tenants created before it existed would otherwise never get it.
HUMAN_REQUESTED = "human_requested"
HUMAN_FALLBACK_TEXT = "Claro. Para hablar con una persona, contacta directamente con {business}."
HUMAN_TEXT = "Claro. Para hablar con una persona de {business}: {contact}"

# Ids of the buttons of the "command or name?" question.
CMD_PAYLOAD = "fp_cmd:"
NAME_PAYLOAD = "fp_name:"

type GlobalCommand = Literal["menu", "opt_out", "opt_in", "human", "ask"]

_OPT_OUT_WORDS = frozenset({"baja", "stop", "parar"})
_OPT_IN_WORDS = frozenset({"alta"})
_HUMAN_WORDS = frozenset(
    {
        "persona",
        "humano",
        "hablar con una persona",
        "hablar con persona",
        "hablar con un humano",
        "hablar con alguien",
    }
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


def global_command(message: IncomingMessage, *, free_text: bool = False) -> GlobalCommand | None:
    """Commands the runtime resolves before the pack, on the normalized text:
    `menu`, `menú`, `inicio` and `/start` → menu; `baja`, `stop`, `parar` → opt_out;
    `alta` → opt_in; `persona`, `humano`, `hablar con una persona`… → human. The
    effective state's notices are sent with any command too.

    With `free_text` (the pack's current step waits for free text, e.g. a name) those
    words could be the answer: the bot never guesses, so the result is `ask` (see
    `ask_result`). `menu` always works. A press of the question's "do it" button
    (`fp_cmd:<command>`) is the command itself; the "it is my name" one
    (`fp_name:<text>`) is no command: `pack_message` turns it into the text."""
    if message.type == "button":
        payload = message.payload or ""
        if payload.startswith(CMD_PAYLOAD):
            return _CMD_BY_PAYLOAD.get(payload.removeprefix(CMD_PAYLOAD))
        return None
    if message.type != "text" or message.text is None:
        return None
    words = message.text.split()
    if words and words[0].split("@")[0].lower() == "/start":  # also "/start ref", "/start@bot"
        return "menu"
    text = normalize(message.text)
    if text in _MENU_WORDS:
        return "menu"
    command = _word_command(text)
    if command is None:
        return None
    return "ask" if free_text else command


_CMD_BY_PAYLOAD: dict[str, GlobalCommand] = {
    "opt_out": "opt_out",
    "opt_in": "opt_in",
    "human": "human",
}


def _word_command(text: str) -> Literal["opt_out", "opt_in", "human"] | None:
    if text in _OPT_OUT_WORDS:
        return "opt_out"
    if text in _OPT_IN_WORDS:
        return "opt_in"
    if text in _HUMAN_WORDS:
        return "human"
    return None


def pack_message(message: IncomingMessage) -> IncomingMessage:
    """What the pack receives when no command applies: the "it is my name" button of
    the `ask` question becomes the text the person had written."""
    if message.type == "button" and (message.payload or "").startswith(NAME_PAYLOAD):
        text = (message.payload or "").removeprefix(NAME_PAYLOAD).strip()
        return IncomingMessage("text", text.capitalize(), None, message.received_at)
    return message


_ASK = {
    "opt_out": ("¿Quieres darte de baja de los avisos o es tu nombre?", "Darme de baja"),
    "opt_in": ("¿Quieres volver a recibir los avisos o es tu nombre?", "Recibir avisos"),
    "human": ("¿Quieres hablar con una persona o es tu nombre?", "Hablar con persona"),
}


def ask_result(message: IncomingMessage) -> PackResult:
    """The text of a command word typed where the pack waits for free text (a name):
    ask what was meant. The state is kept, so "it is my name" continues the booking."""
    text = normalize(message.text or "")
    command = _word_command(text) or "opt_out"
    question, title = _ASK[command]
    return PackResult(
        replies=[
            buttons_msg(
                question,
                [
                    button(f"{CMD_PAYLOAD}{command}", title),
                    button(f"{NAME_PAYLOAD}{text}", "Es mi nombre"),
                ],
            )
        ]
    )


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


def command_result(
    command: Literal["opt_out", "opt_in", "human", "ask"],
    message: IncomingMessage,
    tenant: TenantInfo,
    contact: ContactInfo | None,
) -> PackResult:
    """The result of any global command but `menu`, the same in production and in the
    test harness."""
    if command == "human":
        return human_result(tenant, contact, message.received_at)
    if command == "ask":
        return ask_result(message)
    return opt_result(command)


def recovery_result() -> PackResult:
    """After an unexpected error or the last failed retry: apologise and reset."""
    return PackResult(replies=[Text(RECOVERY_TEXT)], state={})


def human_result(tenant: TenantInfo, contact: ContactInfo | None, now: datetime) -> PackResult:
    """`persona`: the business' own contact details (never invented: without
    `support.human_contact` it only says to contact the business) and a notice to the
    owner, at most one per contact and hour, with no phone or id (only the name the
    contact gave, if any). The state is kept."""
    text = (
        HUMAN_TEXT.format(business=tenant.name, contact=tenant.human_contact)
        if tenant.human_contact
        else HUMAN_FALLBACK_TEXT.format(business=tenant.name)
    )
    actions: list[NotifyOwner] = []
    if contact is not None:
        who = f" ({contact.display_name})" if contact.display_name else ""
        actions.append(
            NotifyOwner(
                HUMAN_REQUESTED,
                f"🙋 Un cliente{who} ha pedido hablar con una persona por el bot de {tenant.name}.",
                f"{HUMAN_REQUESTED}:{contact.id}:{now:%Y%m%d%H}",
            )
        )
    return PackResult(replies=[Text(text)], actions=list(actions))


def first_contact_notice(tenant: TenantInfo) -> Text:
    """First layer of the privacy information (RGPD art. 13): who answers, the purpose,
    the controller, where to read more and how to ask for a person or opt out. Sent
    once per contact."""
    controller = tenant.controller_name or tenant.name
    rights = (
        f"Más información y tus derechos: {tenant.policy_url}."
        if tenant.policy_url
        else "Para ejercer tus derechos (acceso, rectificación, supresión) contacta con el negocio."
    )
    return Text(
        f"Soy el asistente automático de {tenant.name}, no una persona. "
        "Uso tus datos solo para atender lo que me pidas. "
        f"Responsable: {controller}. {rights} "
        "Escribe *PERSONA* para hablar con alguien o *BAJA* para dejar de recibir avisos."
    )
