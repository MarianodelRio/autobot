"""Spanish texts of the salon pack, configurable per tenant."""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from core.dates import format_date_es
from core.proactive import TemplateSpec


class SalonTexts(BaseModel):
    model_config = ConfigDict(
        str_max_length=512, str_min_length=1, str_strip_whitespace=True, extra="forbid"
    )
    welcome: str = "💈 ¡Bienvenido! ¿En qué podemos ayudarte hoy?"
    name_prompt: str = "¿A nombre de quién reservamos? Escribe tu nombre."
    name_text_only: str = "Por favor, escribe tu nombre en un mensaje de texto 🙂"
    no_slots: str = "No hay horarios disponibles para ese día. Prueba con otro día."
    no_days: str = (
        "Ahora mismo no hay ningún día con horarios disponibles. Inténtalo más adelante o llámanos."
    )
    unsupported: str = (
        "No puedo leer audios, imágenes ni stickers 🙂 Usa las opciones o escribe *menú*."
    )
    list_hint: str = "Elige una opción de la lista o escribe *menú*."
    past_booking: str = "Esa cita ya ha pasado, así que no se puede cambiar ni cancelar."
    cancel_kept: str = "Perfecto, tu cita sigue en pie ✅"
    slot_taken: str = "Ese horario ya no está disponible"
    no_bookings: str = "No tienes ninguna cita próxima."
    cancelled: str = "Tu cita ha sido cancelada ✅"
    missing: str = "No se encontró esa cita."
    confirmed: str = "¡Tu cita está confirmada! ✅"
    moved: str = "Tu cita ha sido movida ✅"
    move_cancel_failed: str = (
        "Tu nueva cita está reservada. No hemos podido cancelar la anterior; "
        "hemos avisado al negocio."
    )


TEMPLATE_CONFIRMATION = TemplateSpec(
    name="confirmacion_cita",
    language="es_ES",
    text=(
        "Hola {1}, tu cita ha sido confirmada para el {2} a las {3}. "
        "Si necesitas cancelarla, pulsa el botón."
    ),
    buttons=["Cancelar cita"],
)
TEMPLATE_REMINDER = TemplateSpec(
    name="recordatorio_cita",
    language="es_ES",
    text="Recuerda que tienes cita el {1} a las {2}. ¿Confirmas tu asistencia?",
    buttons=["Confirmar", "Cancelar"],
)


def owner_notice(title: str, name: str, detail: str) -> str:
    """Bold title plus client and detail, for the owner's Telegram notices."""
    return f"*{title}*\n{name} — {detail}"


def booking_text(prefix: str, service_name: str, price: Decimal | None, at: datetime) -> str:
    cost = f" — {price:g}€" if price is not None else ""
    return (
        f"{prefix}\n\n✂️ {service_name}{cost}\n"
        f"📅 {format_date_es(at.date()).capitalize()}\n🕒 {at:%H:%M}\n\n¡Te esperamos! 💈"
    )
