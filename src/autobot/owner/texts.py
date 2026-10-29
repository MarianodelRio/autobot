"""Reply texts of the owner's notify bot
(`docs/mejoras/02-avisos-y-resumenes.md` §6.4). `*bold*` is Telegram's own markup,
which the adapter turns into `<b>`."""

from django.conf import settings

from autobot.tenancy.registry import LoadedTenant

PACK_FAILED = "⚠️ Ahora no puedo leer tu agenda; prueba en unos minutos."


def greeting(tenants: list[LoadedTenant]) -> str:
    if len(tenants) == 1:
        return f"👋 ¡Hola! Soy el asistente de *{tenants[0].info.name}*.\n¿Qué necesitas?"
    return "👋 ¡Hola! Soy tu asistente de Autobot.\n¿Qué necesitas?"


def contact() -> str:
    return (
        "✉️ ¿Dudas, cambios o algo que no va?\n"
        f"Escríbeme a {settings.OWNER_SUPPORT_EMAIL} y te respondo lo antes posible."
    )


def not_linked() -> str:
    where = (
        f"pide tu enlace de activación a {settings.OWNER_SUPPORT_EMAIL}."
        if settings.OWNER_SUPPORT_EMAIL
        else "pide tu enlace de activación a quien te dio de alta."
    )
    return f"🤔 Este chat no está conectado a ningún negocio.\nSi eres cliente de Autobot, {where}"


def linked(tenant: LoadedTenant) -> str:
    return (
        f"✅ ¡Listo! Este chat ya está conectado con *{tenant.info.name}*.\n"
        "Por aquí te llegarán los avisos y resúmenes de tu negocio."
    )


def invite_invalid() -> str:
    where = (
        f"Pide uno nuevo a {settings.OWNER_SUPPORT_EMAIL}."
        if settings.OWNER_SUPPORT_EMAIL
        else "Pide uno nuevo a quien te lo envió."
    )
    return f"⌛ Este enlace ya no es válido. {where}"


def chat_taken() -> str:
    return (
        "⚠️ Este chat ya está conectado con otro negocio. Si necesitas cambiarlo, "
        f"escribe a {settings.OWNER_SUPPORT_EMAIL}."
    )


def not_active(tenant: LoadedTenant) -> str:
    return (
        f"⏸️ El bot de *{tenant.info.name}* todavía no está activo. "
        "Cuando lo esté, aquí verás tus cifras."
    )
