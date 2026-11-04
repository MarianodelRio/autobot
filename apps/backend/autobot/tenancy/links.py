"""A tenant channel's public link (DESIGN §9.4): `wa.me/<display_phone>` or
`t.me/<bot_username>`. Shared by the panel (`GET tenants/{slug}`) and the operator's
`tools/qr.py`, so both show the same link."""

import re

from autobot.tenancy.schema import Channel


def channel_link(channel: Channel) -> str:
    """Use the public phone, never Meta's phone_number_id, or the business bot name."""
    if channel.type == "telegram":
        if not channel.bot_username:
            raise ValueError("Falta channel.bot_username para generar el enlace.")
        return f"https://t.me/{channel.bot_username}"
    phone = channel.display_phone or ""
    if not re.fullmatch(r"\+?[0-9 ()\-.]+", phone):
        raise ValueError("Configura channel.display_phone con el número internacional del negocio.")
    digits = re.sub(r"[^0-9]", "", phone)
    if not re.fullmatch(r"[1-9][0-9]{6,14}", digits):
        raise ValueError(
            "channel.display_phone debe incluir el prefijo internacional (7–15 cifras)."
        )
    return f"https://wa.me/{digits}"
