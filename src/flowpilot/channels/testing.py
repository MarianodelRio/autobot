"""Rendering check for the conversation harness (design.md §17.2): every reply and
proactive message of a scenario is rendered with both adapters, so a pack whose messages
do not fit a channel fails its tests. The root conftest.py registers it in
`core.testing.harness.RENDER_CHECKS`."""

import json

import httpx

from core.serialization import Outbound
from flowpilot.channels.telegram.adapter import TelegramAdapter, overflow
from flowpilot.channels.whatsapp.adapter import WhatsAppAdapter
from flowpilot.tenancy.schema import WhatsAppChannel


def _no_network(request: httpx.Request) -> httpx.Response:
    raise AssertionError("a conversation scenario must not reach the network")


# Only `render` is used; a client that refuses any request makes sure of it.
_CLIENT = httpx.Client(transport=httpx.MockTransport(_no_network))
_WHATSAPP = WhatsAppAdapter(_CLIENT)
_TELEGRAM = TelegramAdapter(_CLIENT)
_CHANNEL = WhatsAppChannel(type="whatsapp", public_id="harness0")


def check_rendering(out: Outbound) -> None:
    problems = overflow(out)
    if problems:
        raise AssertionError(f"does not fit Telegram: {'; '.join(problems)}")
    for rendered in (_WHATSAPP.render(out, _CHANNEL), _TELEGRAM.render(out, None)):
        json.dumps(rendered, allow_nan=False)  # a request body must be JSON
