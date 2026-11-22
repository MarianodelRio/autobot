"""Re-applies the erasures of the suppression ledger over a restored database (ADR-019).

docs/procedimientos/restaurar.md."""

import json
import sys
from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from autobot.management.commands.privacy_ledger_export import MARKER
from autobot.ops.audit import record
from autobot.runtime import privacy, suppressions

KEYS = {"id", "at", "kind", "tenant_id", "contact_id", "channel", "identity_hashes"}


def read_ledger(path: str) -> list[dict[str, Any]]:
    try:
        text = sys.stdin.read() if path == "-" else Path(path).read_text(encoding="utf-8")
        lines = text.splitlines()
    except OSError:
        raise CommandError("No se pudo leer el archivo del libro de supresiones.") from None
    rows: list[dict[str, Any]] = []
    for number, line in enumerate(lines, start=1):
        try:
            row = json.loads(line)
        except ValueError:
            continue  # a log line mixed into the saved stdout
        if not isinstance(row, dict) or row.get("ledger") != MARKER:
            continue
        if not row.keys() >= KEYS or row["kind"] not in (suppressions.FORGET, suppressions.PURGE):
            raise CommandError(f"Línea {number} del libro no válida; no se ha aplicado nada.")
        rows.append(row)
    return rows


class Command(BaseCommand):
    help = "Vuelve a aplicar los olvidos y purgas del libro de supresiones tras restaurar."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--ledger",
            help="Salida guardada de privacy_ledger_export, o - para leerla de stdin.",
        )

    def handle(self, *args: object, **options: object) -> None:
        entries = suppressions.export_rows()
        if options.get("ledger"):
            entries += read_ledger(str(options["ledger"]))
        result = privacy.reapply(entries)
        record(
            actor="command:privacy_reapply",
            action="privacy.reapply",
            summary="Supresiones reaplicadas tras restaurar",
            details=result,
        )
        self.stdout.write(
            "Entradas: {entries}; contactos borrados: {contacts}; negocios purgados: {tenants}; "
            "otras filas: {other_rows}; bloqueadas: {blocked}.".format(**result)
        )
        if result["blocked"]:
            raise CommandError("Hay purgas bloqueadas por trabajos en curso: repite el comando.")
