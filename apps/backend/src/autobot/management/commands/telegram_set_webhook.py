"""`manage.py telegram_set_webhook <slug|demo|notify> [--delete]`: register (or remove)
the webhook of a tenant's own Telegram bot, the demo bot's Telegram door or the notify
bot, with its `secret_token` and only `message` and `callback_query` updates. Needs
PUBLIC_URL."""

from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from autobot.channels.telegram.polling import source
from autobot.ops import tenant_actions
from autobot.tenancy.registry import get_registry

ACTOR = "command:telegram_set_webhook"


class Command(BaseCommand):
    help = "Set or delete the webhook of a tenant's Telegram bot, the demo bot or the notify bot."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("target", help="a tenant slug, `demo` for the demo bot, or `notify`")
        parser.add_argument("--delete", action="store_true", help="remove the webhook")

    def handle(self, *args: Any, **options: Any) -> None:
        target = options["target"]
        slug = None if target == "demo" else target
        # `demo` and `notify` are platform bots, not tenants.
        tenant = None if target in ("demo", "notify") else get_registry().by_slug.get(target)
        try:
            if options["delete"]:
                tenant_actions.delete_telegram_webhook(slug, actor=ACTOR, tenant=tenant)
                self.stdout.write(f"Webhook of {source(slug).name} deleted.")
                return
            url = tenant_actions.set_telegram_webhook(slug, actor=ACTOR, tenant=tenant)
        except tenant_actions.ActionError as e:
            raise CommandError(str(e)) from None
        self.stdout.write(f"Webhook of {source(slug).name} set to {url}")
