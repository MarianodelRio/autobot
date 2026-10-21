"""`migrate` runs as fp_owner by default (design.md §12.2): fp_app cannot do DDL, and
running it on `default` would fail halfway. `--database` still works as usual."""

from django.core.management.base import CommandParser
from django.core.management.commands.migrate import Command as MigrateCommand


class Command(MigrateCommand):
    def add_arguments(self, parser: CommandParser) -> None:
        super().add_arguments(parser)
        parser.set_defaults(database="owner")
