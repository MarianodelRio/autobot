"""Retry a failed, idempotent job by hand (docs/incidencias/cola-y-latido.md)."""

from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from autobot.ops import actions


class Command(BaseCommand):
    help = "Reintenta un trabajo fallido idempotente."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("job_id", type=int)

    def handle(self, *args: Any, **options: Any) -> None:
        result = actions.retry_job(options["job_id"], actor="command:job_retry")
        if not result.ok:
            raise CommandError(result.message)
        self.stdout.write(result.message)
