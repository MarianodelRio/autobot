"""Build a one-time Telegram invite link for a business owner (ADR-007). The code
only ever appears in the caller's own output: never logged or audited."""

from dataclasses import dataclass
from datetime import datetime, timedelta

import httpx
from django.utils import timezone

from autobot.channels.telegram.adapter import TelegramApiError, call
from autobot.owner.links import OWNER_INVITE_DAYS, new_invite, owner_chat
from autobot.runtime.notifications import bot_secrets
from autobot.tenancy.registry import LoadedTenant


class InviteError(Exception):
    """Raised when the invite link cannot be created."""


@dataclass(frozen=True)
class InviteLink:
    url: str
    expires_at: datetime
    replaces_chat: bool


def create_invite_link(tenant: LoadedTenant) -> InviteLink:
    if tenant.document.status == "offboarded":
        raise InviteError("El negocio está dado de baja.")
    bot = bot_secrets()
    if bot is None:
        raise InviteError("Falta NOTIFY_BOT_TOKEN.")
    try:
        with httpx.Client() as client:
            me = call(client, bot, "getMe", {})
    except TelegramApiError as e:
        raise InviteError(f"Telegram rechazó la petición: {e}") from None
    if not isinstance(me, dict) or not isinstance(me.get("username"), str):
        raise InviteError("Telegram no devolvió el nombre del bot.")
    replaces_chat = owner_chat(tenant.id) is not None
    code = new_invite(tenant.id)
    expires_at = timezone.now() + timedelta(days=OWNER_INVITE_DAYS)
    return InviteLink(
        url=f"https://t.me/{me['username']}?start={code}",
        expires_at=expires_at,
        replaces_chat=replaces_chat,
    )
