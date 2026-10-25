"""Run and persist the same checks used by the daily worker health check."""

from django.core.management.base import BaseCommand, CommandError

from flowpilot.ops.health import daily, tenant_health
from flowpilot.tenancy.registry import get_registry


class Command(BaseCommand):
    help = "Comprueba la salud del pack y del canal de un negocio."

    def add_arguments(self, parser: object) -> None:
        from django.core.management.base import CommandParser

        assert isinstance(parser, CommandParser)
        parser.add_argument("slug")

    def handle(self, *args: object, **options: object) -> None:
        tenant = get_registry().by_slug.get(str(options["slug"]))
        if tenant is None:
            raise CommandError("Tenant desconocido.")
        issues = daily(tenant.id, lambda: tenant_health(tenant), force=True)
        for issue in issues:
            self.stdout.write(f"{issue.severity} {issue.code}: {issue.message}")
        if issues:
            raise CommandError("El negocio tiene problemas de salud.")
        self.stdout.write(self.style.SUCCESS("Salud correcta."))
