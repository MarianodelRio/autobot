"""Run and persist the same checks used by the daily worker health check."""

from django.core.management.base import BaseCommand, CommandError, CommandParser

from autobot.management.commands._common import registry_tenant
from autobot.ops.health import daily, tenant_health


class Command(BaseCommand):
    help = "Comprueba la salud del pack y del canal de un negocio."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("slug")

    def handle(self, *args: object, **options: object) -> None:
        tenant = registry_tenant(str(options["slug"]))
        issues = daily(tenant.id, lambda: tenant_health(tenant), force=True)
        for issue in issues:
            self.stdout.write(f"{issue.severity} {issue.code}: {issue.message}")
        if issues:
            raise CommandError("El negocio tiene problemas de salud.")
        self.stdout.write(self.style.SUCCESS("Salud correcta."))
