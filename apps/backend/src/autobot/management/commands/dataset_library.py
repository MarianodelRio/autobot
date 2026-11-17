"""Upload (`push`), download (`pull`) and list named, versioned datasets in the
operator's library (ADR-013), independent of any tenant."""

import json
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from autobot.tenancy import archive, dataset_library


class Command(BaseCommand):
    help = "Sube o lista conjuntos de datos de la biblioteca (ADR-013)."
    requires_system_checks: list[str] = []

    def add_arguments(self, parser: CommandParser) -> None:
        commands = parser.add_subparsers(dest="action", required=True)

        push = commands.add_parser("push")
        push.add_argument("pack")
        push.add_argument("dataset")
        push.add_argument("name")
        push.add_argument("location")
        push.add_argument("--comment", required=True)
        push.add_argument("--base-sha", default=None)
        push.add_argument("--dry-run", action="store_true")

        pull = commands.add_parser("pull")
        pull.add_argument("pack")
        pull.add_argument("dataset")
        pull.add_argument("name")
        pull.add_argument("location")
        pull.add_argument("--version", type=int, default=None)

        listing = commands.add_parser("list")
        listing.add_argument("pack")
        listing.add_argument("dataset")

        sha = commands.add_parser("current-sha")
        sha.add_argument("pack")
        sha.add_argument("dataset")
        sha.add_argument("name")

    def handle(self, *args: Any, **options: Any) -> None:
        action = options["action"]
        try:
            if action == "push":
                self._push(options)
            elif action == "pull":
                self._pull(options)
            elif action == "current-sha":
                entry = dataset_library.latest(options["pack"], options["dataset"], options["name"])
                # Prefixed so a caller that only reads the last stdout line (a
                # subprocess's output otherwise also carries manage.py's own
                # startup log lines) can tell this from "no entry" unambiguously.
                self.stdout.write(f"SHA:{entry.sha256 if entry else ''}")
            else:
                self._list(options["pack"], options["dataset"])
        except dataset_library.LibraryError as error:
            raise CommandError(error.message) from None

    def _push(self, options: dict[str, Any]) -> None:
        pack, dataset, name, location = (
            options["pack"],
            options["dataset"],
            options["name"],
            options["location"],
        )
        with archive.input_directory(location) as directory:
            files = archive.read_files(directory)
        if options["dry_run"]:
            result = dataset_library.preview(pack=pack, dataset=dataset, name=name, files=files)
            if not result.changed:
                self.stdout.write("sin cambios")
            elif result.base_sha:
                self.stdout.write(f"cambiaría (versión base {result.base_sha})")
            else:
                self.stdout.write("cambiaría (entrada nueva)")
            return
        entry = dataset_library.push(
            pack=pack,
            dataset=dataset,
            name=name,
            files=files,
            author="command:dataset_library",
            comment=options["comment"],
            base_sha=options["base_sha"],
        )
        self.stdout.write("sin cambios" if entry is None else f"Subido {name} v{entry.version}")

    def _pull(self, options: dict[str, Any]) -> None:
        entry = dataset_library.get(
            options["pack"], options["dataset"], options["name"], options["version"]
        )
        with archive.output_directory(options["location"]) as directory:
            archive.write_files(directory, entry.files)
        # `-` already streamed the tar.gz straight to stdout.buffer; a text line
        # after it would corrupt that stream.
        if options["location"] != "-":
            self.stdout.write(f"Descargado {entry.name} v{entry.version}")

    def _list(self, pack: str, dataset: str) -> None:
        entries = dataset_library.list_entries(pack, dataset)
        self.stdout.write(
            json.dumps(
                [
                    {
                        "name": e.name,
                        "version": e.version,
                        "sha256": e.sha256,
                        "summary": e.summary,
                        "author": e.author,
                        "comment": e.comment,
                    }
                    for e in entries
                ],
                ensure_ascii=False,
            )
        )
