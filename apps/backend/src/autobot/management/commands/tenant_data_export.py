"""Operator command for data rights and tenant offboarding.

docs/procedimientos/retencion-rgpd.md."""

from django.core.management.base import BaseCommand, CommandParser
from django.db import transaction

from autobot.ops.audit import record_tenant
from autobot.runtime import privacy


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
        record_tenant(
            "command:tenant_data_export",
            "tenant.export",
            tenant,
            "Exportación de datos del negocio",
        )
        self.stdout.write("Exportación guardada en archivo privado.")
