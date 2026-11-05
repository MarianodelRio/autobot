"""Import, export and validate versioned tenant configuration."""

from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from autobot.tenancy import archive, store
from autobot.tenancy.registry import load_registry


class Command(BaseCommand):
    help = "Importa, exporta o valida la configuración versionada."
    requires_system_checks: list[str] = []

    def add_arguments(self, parser: CommandParser) -> None:
        commands = parser.add_subparsers(dest="action", required=True)
        export = commands.add_parser("export")
        export.add_argument("slug")
        export.add_argument("location")
        load = commands.add_parser("import")
        load.add_argument("location")
        load.add_argument("--secrets")
        load.add_argument("--comment", default="")
        validate = commands.add_parser("validate")
        validate.add_argument("--all", action="store_true", required=True)

    def handle(self, *args: Any, **options: Any) -> None:
        from packs.registry import PACKS

        try:
            if options["action"] == "export":
                source = archive.current(options["slug"])
                with archive.output_directory(options["location"]) as directory:
                    archive.write_source(directory, source)
            elif options["action"] == "import":
                with archive.input_directory(options["location"]) as directory:
                    source = archive.read_source(directory, options["secrets"])
                    slug = source.document["slug"]
                    version = store.import_source(
                        source, actor="command:tenant_config", comment=options["comment"]
                    )
                self.stdout.write(f"Imported {slug} v{version}")
            else:
                registry = load_registry(store.current_sources(), PACKS)
                if registry.problems:
                    for slug, problems in registry.problems.items():
                        self.stderr.write(f"{slug}: {'; '.join(problems)}")
                    raise CommandError("Hay configuraciones no válidas")
                self.stdout.write(f"Valid: {len(registry.tenants)} tenant(s)")
        except store.StoreError as error:
            raise archive.command_error(error) from None
