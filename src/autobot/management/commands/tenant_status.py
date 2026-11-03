"""Pause, resume or offboard a tenant, with slug confirmation for offboarding."""

from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from autobot.tenancy import archive, store


class Command(BaseCommand):
    help = "Pausa, reactiva o da de baja un negocio."
    requires_system_checks: list[str] = []

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("slug")
        parser.add_argument("action", choices=["pause", "resume", "offboard"])

    def handle(self, *args: Any, **options: Any) -> None:
        slug, action = options["slug"], options["action"]
        confirmation = None
        if action == "offboard":
            try:
                confirmation = input("Escriba el slug del negocio para confirmar la baja: ")
            except EOFError, KeyboardInterrupt:
                raise CommandError("Baja cancelada") from None
        try:
            version = store.change_status(
                slug, action=action, actor="command:tenant_status", confirm_slug=confirmation
            )
        except store.StoreError as error:
            raise archive.command_error(error) from None
        self.stdout.write(f"Updated {slug} v{version}")
