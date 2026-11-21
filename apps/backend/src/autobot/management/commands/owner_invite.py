"""Generate a one-time link for a business owner to connect their Telegram chat to
the notify bot (ADR-007). The code only ever
appears in this command's own output: never logged."""

from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from autobot.management.commands._common import registry_tenant
from autobot.ops import tenant_actions


class Command(BaseCommand):
    help = "Generate a one-time Telegram link for a business owner."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("slug")

    def handle(self, *args: Any, **options: Any) -> None:
        tenant = registry_tenant(options["slug"])
        try:
            link = tenant_actions.create_owner_invite(tenant, actor="command:owner_invite")
        except tenant_actions.ActionError as e:
            raise CommandError(str(e)) from None
        if link.replaces_chat:
            self.stdout.write("Ya hay un chat conectado; este enlace lo sustituirá cuando se use.")
        expires = link.expires_at.astimezone(tenant.info.timezone)
        self.stdout.write(
            f"Enlace para {tenant.document.name} (caduca el {expires:%d/%m/%Y}): {link.url}"
        )
