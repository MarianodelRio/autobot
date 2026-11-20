"""`manage.py telegram_set_webhook <slug|demo|notify> [--delete]`: register (or remove)
the webhook of a tenant's own Telegram bot, the demo bot's Telegram door or the notify
bot, with its `secret_token` and only `message` and `callback_query` updates. Needs
PUBLIC_URL."""

from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from autobot.channels.telegram.polling import source
from autobot.channels.telegram.registration import WebhookError, register_webhook, remove_webhook
from autobot.ops.audit import record
from autobot.tenancy.registry import get_registry


class Command(BaseCommand):
    help = "Set or delete the webhook of a tenant's Telegram bot, the demo bot or the notify bot."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("target", help="a tenant slug, `demo` for the demo bot, or `notify`")
        parser.add_argument("--delete", action="store_true", help="remove the webhook")

    def handle(self, *args: Any, **options: Any) -> None:
        target = options["target"]
        slug = None if target == "demo" else target
        try:
            if options["delete"]:
                remove_webhook(slug)
                self._audit(target, "tenant.webhook_delete", "Webhook de Telegram eliminado")
                self.stdout.write(f"Webhook of {source(slug).name} deleted.")
                return
            url = register_webhook(slug)
        except (ValueError, WebhookError) as e:
            raise CommandError(str(e)) from None
        self._audit(target, "tenant.webhook_register", "Webhook de Telegram registrado")
        self.stdout.write(f"Webhook of {source(slug).name} set to {url}")

    def _audit(self, target: str, action: str, summary: str) -> None:
        # `demo` and `notify` are platform bots, not tenants: no tenant_id.
        tenant = None if target in ("demo", "notify") else get_registry().by_slug.get(target)
        record(
            actor="command:telegram_set_webhook",
            action=action,
            summary=summary,
            tenant_id=tenant.id if tenant is not None else None,
            target_type="tenant" if tenant is not None else "bot",
            target_id=str(tenant.id) if tenant is not None else target,
        )
