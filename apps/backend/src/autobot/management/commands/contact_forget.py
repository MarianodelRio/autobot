"""Operator command for data rights and tenant offboarding.

docs/procedimientos/retencion-rgpd.md."""

from django.core.management.base import BaseCommand, CommandParser

from autobot.ops.audit import record
from autobot.runtime import privacy


class Command(BaseCommand):
    help = "Gestiona los derechos de datos del negocio."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("slug")
        parser.add_argument("external_id")
        parser.add_argument("--channel", choices=["main", "demo_tg", "demo_wa"])

    def handle(self, *args: object, **options: object) -> None:
        tenant = privacy.tenant_for(str(options["slug"]))
        contact = privacy.contact_for(
            tenant,
            str(options["external_id"]),
            str(options["channel"]) if options.get("channel") else None,
        )
        tenant_id, contact_id = contact.tenant_id, contact.id
        privacy.forget(contact)
        record(
            actor="command:contact_forget",
            action="contact.forget",
            summary="Contacto olvidado (derecho de supresión)",
            tenant_id=tenant_id,
            target_type="contact",
            target_id=str(contact_id),
            details={"contact_id": str(contact_id)},
        )
        self.stdout.write(
            "Contacto borrado. Guarda fuera del servidor el libro: privacy_ledger_export."
        )
