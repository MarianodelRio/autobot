"""Writes the panel API's OpenAPI schema (DESIGN §6.3); `make api` keeps it committed
and in sync, and CI fails if it isn't."""

import json
from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandParser

from autobot.panel.api import api


class Command(BaseCommand):
    help = "Genera el esquema OpenAPI de la API del panel."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("path", type=Path)

    def handle(self, *args: Any, **options: Any) -> None:
        path: Path = options["path"]
        schema = api.get_openapi_schema(path_prefix="")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(schema, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
        self.stdout.write(self.style.SUCCESS(f"Escrito {path}"))
