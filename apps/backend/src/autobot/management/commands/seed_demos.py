"""Seed each pack's initial demo exactly once, preserving later operator changes."""

from typing import Any

from django.core.management.base import BaseCommand
from django.db import transaction

from autobot.tenancy import archive, store
from autobot.tenancy.models import TenantDocumentVersion
from autobot.tenancy.registry import source_from_dir


class Command(BaseCommand):
    help = "Crea los demos iniciales de los packs que aún no tengan versiones."
    requires_system_checks: list[str] = []

    def handle(self, *args: Any, **options: Any) -> None:
        from packs.registry import PACKS

        for pack in PACKS.values():
            if pack.template is None:
                continue
            source = source_from_dir(pack.template)
            try:
                with transaction.atomic(using="owner"):
                    store._lock()
                    if (
                        TenantDocumentVersion.objects.using("owner")
                        .filter(tenant_id=source.document["id"])
                        .exists()
                    ):
                        self.stdout.write(f"exists {source.document['slug']}")
                        continue
                    store.create_tenant(
                        document=source.document,
                        datasets=source.datasets,
                        actor="command:seed_demos",
                        comment="Plantilla inicial",
                        keep_status=True,
                    )
                self.stdout.write(f"created {source.document['slug']}")
            except store.StoreError as error:
                raise archive.command_error(error) from None
