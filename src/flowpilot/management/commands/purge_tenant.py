"""Operator command for design.md §12.3 and §16.2."""

from django.core.management.base import BaseCommand, CommandError, CommandParser

from flowpilot.runtime import privacy


class Command(BaseCommand):
    help = "Gestiona los derechos de datos del negocio."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("slug")

    def handle(self, *args: object, **options: object) -> None:
        tenant = privacy.tenant_for(str(options["slug"]))
        try:
            confirmation = input("Escriba el slug del negocio para confirmar: ")
        except EOFError, KeyboardInterrupt:
            raise CommandError("Borrado cancelado.") from None
        if confirmation != tenant.slug:
            raise CommandError("Confirmación incorrecta: no se ha borrado nada.")
        privacy.purge(tenant)
        self.stdout.write("Datos del negocio borrados.")
