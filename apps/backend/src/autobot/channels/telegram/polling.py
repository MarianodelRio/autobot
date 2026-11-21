"""Long polling for local development: `getUpdates` instead of a
webhook, so no tunnel nor domain is needed. Each update enters **the same way as the
webhook** once authenticated: `selector.store_event` for the demo bot's Telegram door,
`inbox.store_owner_event` for the notify bot, `views.accept` for a business's own bot.
A bot is never polled while it has a webhook (Telegram answers 409):
`telegram_set_webhook <slug|demo|notify> --delete` removes it.
"""

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx
from django.db import InterfaceError, OperationalError, close_old_connections, connections
from procrastinate.exceptions import ProcrastinateException

from autobot.channels import views
from autobot.channels.adapters import TELEGRAM
from autobot.channels.base import InboundItem
from autobot.channels.demo.doors import door
from autobot.channels.demo.selector import store_event
from autobot.channels.telegram.adapter import TelegramApiError, call
from autobot.runtime.models import Channel
from autobot.runtime.notifications import bot_secrets
from autobot.tenancy.registry import get_registry
from autobot.tenancy.schema import TelegramChannel, TelegramSecrets

log = logging.getLogger(__name__)

POLL_TIMEOUT_S = 25  # Telegram holds the request this long when there is nothing
CLIENT_TIMEOUT_S = 35.0  # longer than the poll
ERROR_PAUSE_S = 3.0
# Saving an update fails like this when the database or the queue is unavailable (a
# restart, a dropped connection): the update is not lost, the same offset is asked again
# after a pause. Any other failure (a bug, a body the database refuses) would fail the
# same way every time, so that update is skipped at once.
TRANSIENT_ERRORS = (OperationalError, InterfaceError, ProcrastinateException)
MAX_SAVE_ATTEMPTS = 5  # per update, so a failure that never ends does not block the rest
ALLOWED_UPDATES = ["message", "callback_query"]
DEMO_WEBHOOK_PATH = "webhooks/telegram-demo"
NOTIFY_WEBHOOK_PATH = "webhooks/telegram-notify"


class WebhookActive(Exception):
    """Telegram refuses getUpdates while the bot has a webhook (409)."""


class BotRefused(Exception):
    """The token is not valid (401) or the bot does not exist (404): retrying is useless."""


@dataclass(frozen=True)
class Source:
    name: str  # "demo bot", "notify bot" or the tenant's slug: never the token
    secrets: TelegramSecrets
    accept: Callable[[dict[str, Any]], object]  # the webhook's entry, after authenticity
    webhook_path: str  # for `telegram_set_webhook`, e.g. "webhooks/telegram-demo"


def source(slug: str | None) -> Source:
    """The demo bot's Telegram door (`slug is None`), the notify bot
    (`slug == "notify"`) or the own bot of a tenant whose main channel is Telegram."""
    if slug is None:
        door_ = door(Channel.DEMO_TG)
        if door_ is None:
            raise ValueError("DEMO_TELEGRAM_TOKEN is not set")

        def accept_demo(update: dict[str, Any]) -> None:
            for item in TELEGRAM.parse(update, None):
                if isinstance(item, InboundItem):
                    store_event(door_, item)

        return Source("demo bot", door_.secrets, accept_demo, DEMO_WEBHOOK_PATH)
    if slug == "notify":
        from autobot.owner.inbox import store_owner_event

        secrets = bot_secrets()
        if secrets is None:
            raise ValueError("NOTIFY_BOT_TOKEN is not set")

        def accept_notify(update: dict[str, Any]) -> None:
            for item in TELEGRAM.parse(update, None):
                if isinstance(item, InboundItem):
                    store_owner_event(item)

        return Source("notify bot", secrets, accept_notify, NOTIFY_WEBHOOK_PATH)
    return tenant_source(slug)


def tenant_source(slug: str) -> Source:
    """The own bot of a tenant whose main channel is Telegram. Never the demo nor the
    notify bot, whatever the slug is (the panel resolves through here)."""
    found = get_registry().by_slug.get(slug)
    if found is None:
        raise ValueError(f"no tenant {slug!r}")
    channel = found.document.channel
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

    return Source(slug, tenant.secrets, accept, f"webhooks/telegram/{channel.public_id}")


@dataclass
class _Progress:
    offset: int | None = None  # the next update to ask for
    failing: int | None = None  # the update_id that failed to be saved...
    failures: int = 0  # ...and how often


def poll(
    source: Source,
    client: httpx.Client,
    *,
    stop: Callable[[], bool] = lambda: False,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """Fetch updates until `stop()`. The offset only moves past an update once it is
    saved: if the database or the queue is down it is asked again after a pause (up to
    `MAX_SAVE_ATTEMPTS` times; the connections are dropped so they are opened anew). An
    update that fails for any other reason is logged and skipped, never blocking the next
    ones. Stale connections are closed on every round, as a long-running worker does."""
    progress = _Progress()
    while not stop():
        close_old_connections()
        params: dict[str, Any] = {"timeout": POLL_TIMEOUT_S, "allowed_updates": ALLOWED_UPDATES}
        if progress.offset is not None:
            params["offset"] = progress.offset
        try:
            updates = call(client, source.secrets, "getUpdates", params, CLIENT_TIMEOUT_S)
        except TelegramApiError as e:
            _backoff(source, e, sleep)
            continue
        _handle_updates(source, updates if isinstance(updates, list) else [], progress, sleep)


def _backoff(source: Source, error: TelegramApiError, sleep: Callable[[float], None]) -> None:
    """A failed `getUpdates`: a webhook or a refused token ends the polling; anything
    else is retried after a pause."""
    if error.status == 409:
        raise WebhookActive(source.name) from None
    if error.status in (401, 404):
        raise BotRefused(source.name) from None
    log.warning("getUpdates of %s failed (%s): retrying", source.name, error)
    sleep(ERROR_PAUSE_S)


def _handle_updates(
    source: Source, updates: list[Any], progress: _Progress, sleep: Callable[[float], None]
) -> None:
    for update in updates:
        if not isinstance(update, dict) or not isinstance(update.get("update_id"), int):
            continue
        update_id: int = update["update_id"]
        try:
            source.accept(update)
        except TRANSIENT_ERRORS as e:
            progress.failures = progress.failures + 1 if progress.failing == update_id else 1
            progress.failing = update_id
            connections.close_all()
            if progress.failures < MAX_SAVE_ATTEMPTS:
                log.warning(
                    "update of %s not saved (%s): asking for it again",
                    source.name,
                    type(e).__name__,
                )
                progress.offset = update_id  # not past it: Telegram sends it again
                sleep(ERROR_PAUSE_S)
                return
            log.error("update of %s dropped after %d attempts", source.name, progress.failures)
        except Exception as e:
            # Unlike the webhook (503, so Telegram retries), retrying would fail the
            # same way: in local development this update is lost.
            log.error("update of %s not saved: %s", source.name, type(e).__name__)
        progress.offset = update_id + 1
