"""Operator command for data rights and tenant offboarding.

docs/procedimientos/retencion-rgpd.md."""

from django.core.management.base import BaseCommand, CommandParser
from django.db import transaction

from autobot.ops.audit import record
from autobot.runtime import privacy


class Command(BaseCommand):
    help = "Gestiona los derechos de datos del negocio."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("slug")
        parser.add_argument("external_id")
        parser.add_argument("--channel", choices=["main", "demo_tg", "demo_wa"])
        parser.add_argument("--output", required=True)

    def handle(self, *args: object, **options: object) -> None:
        tenant = privacy.tenant_for(str(options["slug"]))
        contact = privacy.contact_for(
            tenant,
            str(options["external_id"]),
            str(options["channel"]) if options.get("channel") else None,
        )
        with transaction.atomic(using="owner"):
            data = privacy.export_data(tenant, contact)
        privacy.write_private(str(options["output"]), data)
        record(
            actor="command:contact_export",
            action="contact.export",
            summary="Exportación de datos del contacto",
            tenant_id=contact.tenant_id,
            target_type="contact",
            target_id=str(contact.id),
            details={"contact_id": str(contact.id)},
        )
        self.stdout.write("Exportación guardada en archivo privado.")
