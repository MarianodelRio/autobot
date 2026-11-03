"""Import and export the current version of one tenant dataset."""

from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from autobot.tenancy import archive, store


class Command(BaseCommand):
    help = "Importa o exporta un dataset versionado (directorio o tar.gz)."
    requires_system_checks: list[str] = []

    def add_arguments(self, parser: CommandParser) -> None:
        commands = parser.add_subparsers(dest="action", required=True)
        for action in ("import", "export"):
            child = commands.add_parser(action)
            child.add_argument("slug")
            child.add_argument("name")
            child.add_argument("location")
            if action == "import":
                child.add_argument("--comment", required=True)

    def handle(self, *args: Any, **options: Any) -> None:
        try:
            slug, name, location = options["slug"], options["name"], options["location"]
            if options["action"] == "export":
                source = archive.current(slug)
                if name not in source.datasets:
                    raise CommandError("No se encuentra el dataset")
                with archive.output_directory(location) as directory:
                    archive.write_files(directory, source.datasets[name])
            else:
                with archive.input_directory(location) as directory:
                    version = store.import_dataset(
                        slug,
                        name,
                        archive.read_files(directory),
                        actor="command:tenant_dataset",
                        comment=options["comment"],
                    )
                self.stdout.write(
                    "sin cambios" if version is None else f"Imported {name} v{version}"
                )
        except store.StoreError as error:
            raise archive.command_error(error) from None
