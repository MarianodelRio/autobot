"""`manage.py telegram_poll [<slug>]`: long polling of the test bot (by default) or of a
tenant's own Telegram bot, for local development (design.md §6.4, §16.3). The worker
must be running to process what it receives."""

from typing import Any

import httpx
from django.core.management.base import BaseCommand, CommandError, CommandParser

from flowpilot.channels.telegram.polling import (
    CLIENT_TIMEOUT_S,
    BotRefused,
    WebhookActive,
    poll,
    source,
)


class Command(BaseCommand):
    help = "Receive a Telegram bot's updates by long polling (local development)."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("slug", nargs="?", help="a tenant with a Telegram main channel")

    def handle(self, *args: Any, **options: Any) -> None:
        try:
            bot = source(options["slug"])
        except ValueError as e:
            raise CommandError(str(e)) from None
        self.stdout.write(f"Polling {bot.name}. Ctrl+C to stop.")
        try:
            with httpx.Client(timeout=CLIENT_TIMEOUT_S) as client:
                poll(bot, client)
        except WebhookActive:
            target = options["slug"] or "test"
            raise CommandError(
                f"{bot.name} has a webhook: Telegram does not allow polling at the same time."
                f" Remove it with `manage.py telegram_set_webhook {target} --delete`"
                " (never for a bot the server uses)."
            ) from None
        except BotRefused:
            raise CommandError(f"Telegram refuses the token of {bot.name}: check it.") from None
        except KeyboardInterrupt:
            self.stdout.write("Stopped.")
