"""`manage.py telegram_set_webhook <slug|demo|notify> [--delete]`: register (or remove)
the webhook of a tenant's own Telegram bot, the demo bot's Telegram door or the notify
bot, with its `secret_token` and only `message` and `callback_query` updates. Needs
PUBLIC_URL."""

from typing import Any

import httpx
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError, CommandParser

from autobot.channels.telegram.adapter import TelegramApiError, call
from autobot.channels.telegram.polling import ALLOWED_UPDATES, source


class Command(BaseCommand):
    help = "Set or delete the webhook of a tenant's Telegram bot, the demo bot or the notify bot."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("target", help="a tenant slug, `demo` for the demo bot, or `notify`")
        parser.add_argument("--delete", action="store_true", help="remove the webhook")

    def handle(self, *args: Any, **options: Any) -> None:
        target = options["target"]
        slug = None if target == "demo" else target
        try:
            bot = source(slug)
        except ValueError as e:
            raise CommandError(str(e)) from None
        with httpx.Client() as client:
            try:
                if options["delete"]:
                    call(client, bot.secrets, "deleteWebhook", {})
                    self.stdout.write(f"Webhook of {bot.name} deleted.")
                    return
                url = self._url(bot.webhook_path)
                if slug is None and not settings.DEMO_TELEGRAM_WEBHOOK_SECRET:
                    raise CommandError("DEMO_TELEGRAM_WEBHOOK_SECRET is not set")
                if target == "notify" and not settings.NOTIFY_BOT_WEBHOOK_SECRET:
                    raise CommandError("NOTIFY_BOT_WEBHOOK_SECRET is not set")
                params = {
                    "url": url,
                    "secret_token": bot.secrets.webhook_secret.get_secret_value(),
                    "allowed_updates": ALLOWED_UPDATES,
                }
                call(client, bot.secrets, "setWebhook", params)
            except TelegramApiError as e:
                raise CommandError(f"Telegram refused it: {e}") from None
        self.stdout.write(f"Webhook of {bot.name} set to {url}")

    def _url(self, webhook_path: str) -> str:
        base = settings.PUBLIC_URL.rstrip("/")
        if not base:
            raise CommandError("PUBLIC_URL is not set (e.g. https://api.<dominio>)")
        return f"{base}/{webhook_path}"
