"""The adapter, channel description and secrets of each conversation channel
(design.md §6.2, §6.6): `main` is the tenant's own channel; `test` is the platform's
test bot (§6.5), wired in T-3.8."""

from dataclasses import dataclass
from typing import Any

from flowpilot.channels.base import ChannelAdapter
from flowpilot.channels.telegram import TelegramAdapter
from flowpilot.channels.whatsapp import WhatsAppAdapter
from flowpilot.runtime.models import Channel
from flowpilot.tenancy.registry import LoadedTenant

WHATSAPP = WhatsAppAdapter()
TELEGRAM = TelegramAdapter()


@dataclass(frozen=True)
class Endpoint:
    adapter: ChannelAdapter[Any, Any]
    channel: Any  # the tenant.yaml channel, or None for the test bot
    secrets: Any


def endpoint(tenant: LoadedTenant, channel: str) -> Endpoint:
    if channel == Channel.MAIN:
        adapter: ChannelAdapter[Any, Any] = (
            WHATSAPP if tenant.file.channel.type == "whatsapp" else TELEGRAM
        )
        return Endpoint(adapter, tenant.file.channel, tenant.secrets)
    raise NotImplementedError("the test bot channel arrives with T-3.8")
