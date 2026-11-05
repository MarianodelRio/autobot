"""`manage.py apply_grants`: reapply the desired PostgreSQL permissions
(autobot/db/grants.py). Run after `migrate` and after a restore, since
pg_restore --no-acl drops them."""

from typing import Any

from django.core.management.base import BaseCommand
from django.db import connections

from autobot.db import grants


class Command(BaseCommand):
    help = "Reapply the desired PostgreSQL permissions."

    def handle(self, *args: Any, **options: Any) -> None:
        grants.apply(connections["owner"])
        self.stdout.write("Permisos aplicados")
