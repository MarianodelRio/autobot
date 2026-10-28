"""The demo bot's two doors: Telegram and WhatsApp. Each is a channel of the
platform (not of any tenant) with its own secrets and closed user list; the demo
selector of `selector.py` picks the tenant once a person has gone through a door.
"""

import secrets as random_secrets
from dataclasses import dataclass
from functools import cache
from typing import Any

from django.conf import settings

from autobot.channels.base import ChannelAdapter, InboundItem
from autobot.runtime.models import Channel
from autobot.tenancy.schema import TelegramSecrets, WhatsAppChannel, WhatsAppSecrets


@dataclass(frozen=True)
class Door:
    channel: Channel
    adapter: ChannelAdapter[Any, Any]
    description: Any  # the channel description the adapter expects, or None
    secrets: Any
    users: frozenset[str]  # closed list: only these may use this door


def _telegram_door() -> Door | None:
    from autobot.channels.adapters import TELEGRAM

    if not settings.DEMO_TELEGRAM_TOKEN:
        return None
    users = frozenset(str(user_id) for user_id in settings.DEMO_TELEGRAM_USERS)
    return Door(
        channel=Channel.DEMO_TG,
        adapter=TELEGRAM,
        description=None,
        secrets=TelegramSecrets.model_validate(
            {
                "bot_token": settings.DEMO_TELEGRAM_TOKEN,
                "webhook_secret": settings.DEMO_TELEGRAM_WEBHOOK_SECRET
                or random_secrets.token_urlsafe(32),
            }
        ),
        users=users,
    )


def _whatsapp_door() -> Door | None:
    from autobot.channels.adapters import WHATSAPP

    required = (
        settings.DEMO_WHATSAPP_PHONE_NUMBER_ID,
        settings.DEMO_WHATSAPP_WABA_ID,
        settings.DEMO_WHATSAPP_APP_SECRET,
        settings.DEMO_WHATSAPP_ACCESS_TOKEN,
        settings.DEMO_WHATSAPP_VERIFY_TOKEN,
    )
    if not all(required):
        return None
    return Door(
        channel=Channel.DEMO_WA,
        adapter=WHATSAPP,
        description=WhatsAppChannel(
            type="whatsapp",
            public_id="demowhatsapp",
            app_id=None,
            waba_id=settings.DEMO_WHATSAPP_WABA_ID,
            phone_number_id=settings.DEMO_WHATSAPP_PHONE_NUMBER_ID,
            display_phone=settings.DEMO_WHATSAPP_DISPLAY_PHONE or None,
        ),
        secrets=WhatsAppSecrets.model_validate(
            {
                "app_secret": settings.DEMO_WHATSAPP_APP_SECRET,
                "access_token": settings.DEMO_WHATSAPP_ACCESS_TOKEN,
                "verify_token": settings.DEMO_WHATSAPP_VERIFY_TOKEN,
            }
        ),
        users=frozenset(settings.DEMO_WHATSAPP_USERS),
    )


@cache
def door(channel: Channel) -> Door | None:
    """The door of `channel`, or None if it is off (no token/ids configured)."""
    if channel == Channel.DEMO_TG:
        return _telegram_door()
    return _whatsapp_door()


def allowed_identity(door: Door, external_id: str, phone: str | None) -> bool:
    """Is this person in the door's closed list, by their id or (WhatsApp) phone?"""
    if door.channel == Channel.DEMO_TG:
        return external_id in door.users
    digits = (phone or "").removeprefix("+")
    return external_id in door.users or (bool(digits) and digits in door.users)


def allowed(door: Door, item: InboundItem) -> bool:
    return allowed_identity(door, item.external_id, item.phone)
