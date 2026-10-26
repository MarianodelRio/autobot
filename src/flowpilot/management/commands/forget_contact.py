"""Operator command for data rights and tenant offboarding (docs/runbooks/retencion-rgpd.md)."""

from django.core.management.base import BaseCommand, CommandParser

from flowpilot.runtime import privacy


class Command(BaseCommand):
    help = "Gestiona los derechos de datos del negocio."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("slug")
        parser.add_argument("external_id")
        parser.add_argument("--channel", choices=["main", "test"])

    def handle(self, *args: object, **options: object) -> None:
        tenant = privacy.tenant_for(str(options["slug"]))
        contact = privacy.contact_for(
            tenant,
            str(options["external_id"]),
            str(options["channel"]) if options.get("channel") else None,
        )
        privacy.forget(contact)
        self.stdout.write("Contacto borrado.")
