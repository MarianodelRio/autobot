"""Long polling for local development: `getUpdates` instead of a
webhook, so no tunnel nor domain is needed. Each update enters **the same way as the
webhook** once authenticated: `selector.store_event` for the demo bot's Telegram door,
`views.accept` for a business's own bot. A bot is never polled while it has a webhook
(Telegram answers 409): `telegram_set_webhook <slug|demo> --delete` removes it.
"""

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx

from autobot.channels import views
from autobot.channels.adapters import TELEGRAM
from autobot.channels.base import InboundItem
from autobot.channels.demo.doors import door
from autobot.channels.demo.selector import store_event
from autobot.channels.telegram.adapter import TelegramApiError, call
from autobot.runtime.models import Channel
from autobot.tenancy.registry import get_registry
from autobot.tenancy.schema import TelegramChannel, TelegramSecrets

log = logging.getLogger(__name__)

POLL_TIMEOUT_S = 25  # Telegram holds the request this long when there is nothing
CLIENT_TIMEOUT_S = 35.0  # longer than the poll
ERROR_PAUSE_S = 3.0
ALLOWED_UPDATES = ["message", "callback_query"]


class WebhookActive(Exception):
    """Telegram refuses getUpdates while the bot has a webhook (409)."""


class BotRefused(Exception):
    """The token is not valid (401) or the bot does not exist (404): retrying is useless."""


@dataclass(frozen=True)
class Source:
    name: str  # "demo bot" or the tenant's slug: never the token
    secrets: TelegramSecrets
    accept: Callable[[dict[str, Any]], object]  # the webhook's entry, after authenticity
    public_id: str | None = None  # the tenant's, for its webhook URL


def source(slug: str | None) -> Source:
    """The demo bot's Telegram door (no slug) or the own bot of a tenant whose main
    channel is Telegram."""
    if slug is None:
        door_ = door(Channel.DEMO_TG)
        if door_ is None:
            raise ValueError("DEMO_TELEGRAM_TOKEN is not set")

        def accept_demo(update: dict[str, Any]) -> None:
            for item in TELEGRAM.parse(update, None):
                if isinstance(item, InboundItem):
                    store_event(door_, item)

        return Source("demo bot", door_.secrets, accept_demo)
    found = get_registry().by_slug.get(slug)
    if found is None:
        raise ValueError(f"no tenant {slug!r}")
    channel = found.file.channel
    if channel is None or not isinstance(channel, TelegramChannel):
        raise ValueError(f"tenant {slug} has no enabled Telegram main channel")
    # The same tenant the webhook would accept: Telegram channel enabled (ids and
    # secrets) and not ambiguous; otherwise its webhook would answer 404.
    tenant = views.main_channel_tenant("telegram", channel.public_id)
    if tenant is not found:
        raise ValueError(f"tenant {slug} has no enabled Telegram main channel")
    assert isinstance(tenant.secrets, TelegramSecrets)

    def accept(update: dict[str, Any]) -> None:
        views.accept(tenant, update, lambda body: TELEGRAM.parse(body, channel))

    return Source(slug, tenant.secrets, accept, channel.public_id)


def poll(
    source: Source,
    client: httpx.Client,
    *,
    stop: Callable[[], bool] = lambda: False,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """Fetch updates until `stop()`. The offset always moves on, even if an update
    fails: a failure is logged and never blocks the next ones."""
    offset: int | None = None
    while not stop():
        params: dict[str, Any] = {"timeout": POLL_TIMEOUT_S, "allowed_updates": ALLOWED_UPDATES}
        if offset is not None:
            params["offset"] = offset
        try:
            updates = call(client, source.secrets, "getUpdates", params, CLIENT_TIMEOUT_S)
        except TelegramApiError as e:
            if e.status == 409:
                raise WebhookActive(source.name) from None
            if e.status in (401, 404):
                raise BotRefused(source.name) from None
            log.warning("getUpdates of %s failed (%s): retrying", source.name, e)
            sleep(ERROR_PAUSE_S)
            continue
        for update in updates if isinstance(updates, list) else []:
            if not isinstance(update, dict) or not isinstance(update.get("update_id"), int):
                continue
            offset = update["update_id"] + 1
            try:
                source.accept(update)
            except Exception as e:
                # Unlike the webhook (503, so Telegram retries), the offset has moved on:
                # in local development this update is lost.
                log.error("update of %s not saved: %s", source.name, type(e).__name__)
