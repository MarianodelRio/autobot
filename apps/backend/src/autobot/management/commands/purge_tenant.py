"""Operator command for data rights and tenant offboarding (docs/runbooks/retencion-rgpd.md)."""

from django.core.management.base import BaseCommand, CommandError, CommandParser

from autobot.runtime import privacy


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
