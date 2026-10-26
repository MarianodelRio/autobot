"""The adapter, channel description and secrets of each conversation channel:
`main` is the tenant's own channel; `demo_tg`/`demo_wa` are the platform's demo
doors (`channels/demo/doors.py`), shared by every demo tenant."""

from dataclasses import dataclass
from typing import Any

from flowpilot.channels.base import ChannelAdapter
from flowpilot.channels.demo.doors import door
from flowpilot.channels.telegram import TelegramAdapter
from flowpilot.channels.whatsapp import WhatsAppAdapter
from flowpilot.runtime.models import Channel
from flowpilot.tenancy.registry import LoadedTenant

WHATSAPP = WhatsAppAdapter()
TELEGRAM = TelegramAdapter()


@dataclass(frozen=True)
class Endpoint:
    adapter: ChannelAdapter[Any, Any]
    channel: Any  # the tenant.yaml channel, or the demo door's description
    secrets: Any


def endpoint(tenant: LoadedTenant, channel: str) -> Endpoint:
    if channel == Channel.MAIN:
        assert tenant.file.channel is not None  # a demo tenant has no main channel
        adapter: ChannelAdapter[Any, Any] = (
            WHATSAPP if tenant.file.channel.type == "whatsapp" else TELEGRAM
        )
        return Endpoint(adapter, tenant.file.channel, tenant.secrets)
    # A demo door always talks through the platform's own credentials, whatever the
    # tenant's main channel is (a demo tenant has none): never a business's own bot.
    found = door(Channel(channel))
    demo_adapter: ChannelAdapter[Any, Any] = WHATSAPP if channel == Channel.DEMO_WA else TELEGRAM
    if found is None:  # the door is off: fail to send, as if its token were missing
        return Endpoint(demo_adapter, None, None)
    return Endpoint(found.adapter, found.description, found.secrets)
