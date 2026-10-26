"""The adapter, channel description and secrets of each conversation channel:
`main` is the tenant's own channel; `test` is the platform's test bot."""

import secrets
from dataclasses import dataclass
from functools import cache
from typing import Any

from django.conf import settings

from flowpilot.channels.base import ChannelAdapter
from flowpilot.channels.telegram import TelegramAdapter
from flowpilot.channels.whatsapp import WhatsAppAdapter
from flowpilot.runtime.models import Channel
from flowpilot.tenancy.registry import LoadedTenant
from flowpilot.tenancy.schema import TelegramSecrets

WHATSAPP = WhatsAppAdapter()
TELEGRAM = TelegramAdapter()


@dataclass(frozen=True)
class Endpoint:
    adapter: ChannelAdapter[Any, Any]
    channel: Any  # the tenant.yaml channel, or None for the test bot
    secrets: Any


def endpoint(tenant: LoadedTenant, channel: str) -> Endpoint:
    if channel == Channel.MAIN:
        assert tenant.file.channel is not None  # a demo tenant has no main channel
        adapter: ChannelAdapter[Any, Any] = (
            WHATSAPP if tenant.file.channel.type == "whatsapp" else TELEGRAM
        )
        return Endpoint(adapter, tenant.file.channel, tenant.secrets)
    # The test channel always talks through the platform's test bot, whatever the
    # tenant's main channel is: never WhatsApp nor the business's own bot.
    return Endpoint(TELEGRAM, None, test_bot_secrets())


@cache
def test_bot_secrets() -> TelegramSecrets | None:
    """The test bot's secrets, or None if it has no token. Without a webhook secret the
    webhook is off (the view checks the setting), so a random one fills the field."""
    if not settings.TEST_BOT_TOKEN:
        return None
    return TelegramSecrets.model_validate(
        {
            "bot_token": settings.TEST_BOT_TOKEN,
            "webhook_secret": settings.TEST_BOT_WEBHOOK_SECRET or secrets.token_urlsafe(32),
        }
    )
