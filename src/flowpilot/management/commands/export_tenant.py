"""Operator command for design.md §12.3 and §16.2."""

from django.core.management.base import BaseCommand, CommandParser
from django.db import transaction

from flowpilot.runtime import privacy


class Command(BaseCommand):
    help = "Gestiona los derechos de datos del negocio."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("slug")
        parser.add_argument("--output", required=True)

    def handle(self, *args: object, **options: object) -> None:
        tenant = privacy.tenant_for(str(options["slug"]))
        with transaction.atomic(using="owner"):
            data = privacy.export_data(tenant)
        privacy.write_private(str(options["output"]), data)
        self.stdout.write("Exportación guardada en archivo privado.")
