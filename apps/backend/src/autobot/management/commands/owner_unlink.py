"""Disconnect a business owner's Telegram chat (change of owner, or a GDPR
request) (ADR-007)."""

from typing import Any

from django.core.management.base import BaseCommand, CommandParser

from autobot.management.commands._common import registry_tenant
from autobot.ops import tenant_actions


class Command(BaseCommand):
    help = "Disconnect a business owner's Telegram chat."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("slug")

    def handle(self, *args: Any, **options: Any) -> None:
        tenant = registry_tenant(options["slug"])
        had_chat = tenant_actions.unlink_owner(tenant, actor="command:owner_unlink")
        if had_chat:
            self.stdout.write(f"Chat de {tenant.document.name} desconectado.")
        else:
            self.stdout.write(f"{tenant.document.name} no tenía ningún chat conectado.")
