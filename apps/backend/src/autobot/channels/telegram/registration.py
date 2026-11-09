"""Register or remove the Telegram webhook of a tenant's own bot, the demo bot's
Telegram door (`slug is None`) or the notify bot (`slug == "notify"`). Needs
PUBLIC_URL."""

import httpx
from django.conf import settings

from autobot.channels.telegram.adapter import TelegramApiError, call
from autobot.channels.telegram.polling import ALLOWED_UPDATES, source


class WebhookError(Exception):
    """Raised when the webhook cannot be registered or removed."""


def _url(webhook_path: str) -> str:
    base = settings.PUBLIC_URL.rstrip("/")
    if not base:
        raise WebhookError("PUBLIC_URL is not set (e.g. https://api.<dominio>)")
    return f"{base}/{webhook_path}"


def register_webhook(slug: str | None) -> str:
    """Sets the webhook and returns the url it was set to."""
    try:
        bot = source(slug)
    except ValueError as e:
        raise WebhookError(str(e)) from None
    url = _url(bot.webhook_path)
    if slug is None and not settings.DEMO_TELEGRAM_WEBHOOK_SECRET:
        raise WebhookError("DEMO_TELEGRAM_WEBHOOK_SECRET is not set")
    if slug == "notify" and not settings.NOTIFY_BOT_WEBHOOK_SECRET:
        raise WebhookError("NOTIFY_BOT_WEBHOOK_SECRET is not set")
    params = {
        "url": url,
        "secret_token": bot.secrets.webhook_secret.get_secret_value(),
        "allowed_updates": ALLOWED_UPDATES,
    }
    with httpx.Client() as client:
        try:
            call(client, bot.secrets, "setWebhook", params)
        except TelegramApiError as e:
            raise WebhookError(f"Telegram refused it: {e}") from None
    return url


def remove_webhook(slug: str | None) -> None:
    try:
        bot = source(slug)
    except ValueError as e:
        raise WebhookError(str(e)) from None
    with httpx.Client() as client:
        try:
            call(client, bot.secrets, "deleteWebhook", {})
        except TelegramApiError as e:
            raise WebhookError(f"Telegram refused it: {e}") from None
