"""Writes the suppression ledger (ADR-019) as JSON lines to stdout.

Keep the output outside the server: `privacy_reapply` needs it after a restore.
docs/procedimientos/restaurar.md."""

import json

from django.core.management.base import BaseCommand

from autobot.runtime import suppressions

MARKER = "privacy.v1"  # the startup logs also go to stdout: readers keep only marked lines


class Command(BaseCommand):
    help = "Exporta el libro de supresiones (JSON lines, sin datos personales) a stdout."

    def handle(self, *args: object, **options: object) -> None:
        for row in suppressions.export_rows():
            self.stdout.write(json.dumps({"ledger": MARKER, **row}, ensure_ascii=False))
