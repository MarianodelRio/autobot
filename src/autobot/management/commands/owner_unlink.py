"""Disconnect a business owner's Telegram chat (change of owner, or a GDPR
request) (`docs/mejoras/02-avisos-y-resumenes.md` §5.2)."""

from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from autobot.owner.links import unlink
from autobot.tenancy.registry import get_registry


class Command(BaseCommand):
    help = "Disconnect a business owner's Telegram chat."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("slug")

    def handle(self, *args: Any, **options: Any) -> None:
        tenant = get_registry().by_slug.get(options["slug"])
        if tenant is None:
            raise CommandError("Negocio desconocido.")
        if unlink(tenant.id):
            self.stdout.write(f"Chat de {tenant.file.name} desconectado.")
        else:
            self.stdout.write(f"{tenant.file.name} no tenía ningún chat conectado.")
