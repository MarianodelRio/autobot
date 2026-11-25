"""What a rejected send means, in the operator's words (ADR-031).

The channel adapters read the stored `OutboundMessage.last_error` into an error class
(`channels.adapters.error_class`; the provider formats stay in their adapters). This module
adds the classes that come from the platform itself and gives each class its Spanish title
and one-line advice."""

import re
from dataclasses import dataclass
from typing import Literal

from autobot.channels.adapters import error_class as channel_error_class
from autobot.channels.base import ChannelType, ErrorClass

type SendErrorClass = (
    ErrorClass | Literal["expired_payload", "channel_disabled"]
)  # the last two come from the platform, not from a provider

# Internal `last_error` texts (runtime/outbound.py), whatever the channel.
_PAYLOAD_EXPIRED = "payload expired"
_CHANNEL_OFF = ("main channel disabled", "channel has no phone_number_id")
_RETRY_LATER_RATE = "retry later (rate)"
_AUTH_PREFIX = "auth:"  # `Rejected(kind="auth")`, runtime/outbound.py AUTH_FAILURE_PREFIX
_CODE = re.compile(r"(?:error |status failed: )(\d+)")


@dataclass(frozen=True)
class SendError:
    cls: SendErrorClass
    title: str
    advice: str


_TEXTS: dict[SendErrorClass, tuple[str, str]] = {
    "outside_window": (
        "Fuera de la ventana de 24 h",
        "Fuera de la ventana de 24 h de WhatsApp: solo se puede escribir con una plantilla"
        " aprobada. Reintentar no sirve.",
    ),
    "undeliverable": (
        "Número no válido",
        "El número no es válido o no tiene WhatsApp. Reintentar no sirve.",
    ),
    "blocked": ("Bot bloqueado", "La persona ha bloqueado el bot."),
    "auth": (
        "Credencial rechazada",
        "El proveedor rechaza la credencial del canal: revisa el token.",
    ),
    "rate": (
        "Límite de envío",
        "Límite de envío del proveedor: se reintenta solo.",
    ),
    "marketing_declined": (
        "Marketing no entregado",
        "WhatsApp no entregó un mensaje de marketing a esta persona. Reintentar no sirve.",
    ),
    "spam_limit": (
        "Límite por spam",
        "WhatsApp limita los envíos por calidad del número. No insistas: empeora su valoración.",
    ),
    "expired_payload": (
        "Contenido caducado",
        "El contenido del mensaje ya no está disponible (se borra a los 30 días).",
    ),
    "channel_disabled": (
        "Canal desactivado",
        "El canal del negocio estaba desactivado o sin configurar al enviar.",
    ),
    "other": ("Rechazado", "Rechazado por el proveedor."),
}


def classify(channel_type: ChannelType, last_error: str) -> SendErrorClass:
    """The class of a stored `last_error`: the platform's own texts first, then the
    adapter of the message's channel."""
    if last_error.startswith(_AUTH_PREFIX):
        return "auth"
    if _PAYLOAD_EXPIRED in last_error:
        return "expired_payload"
    if any(text in last_error for text in _CHANNEL_OFF):
        return "channel_disabled"
    if last_error == _RETRY_LATER_RATE:
        return "rate"
    return channel_error_class(channel_type, last_error)


def describe(cls: SendErrorClass, last_error: str = "") -> SendError:
    """Title and advice of a class; `other` carries the provider's code when there is one."""
    title, advice = _TEXTS[cls]
    if cls == "other" and (match := _CODE.search(last_error)) is not None:
        advice = f"Rechazado por el proveedor (código {match[1]})."
    return SendError(cls, title, advice)
