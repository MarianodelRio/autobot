"""Seed each pack's initial demo exactly once, preserving later operator changes."""

from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction

from autobot.tenancy import archive, dataset_library, store
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
            if pack.name == "salon" and source.document:
                if settings.DEMO_SALON_CALENDAR_ID:
                    source.document["config"]["calendar_id"] = settings.DEMO_SALON_CALENDAR_ID
                else:
                    self.stderr.write(
                        "DEMO_SALON_CALENDAR_ID is empty: a new salon demo keeps the "
                        "template's placeholder calendar and cannot book."
                    )
            # ADR-013: the demo's own dataset is just another library entry
            # ("demo"), not a special case of its own — the demo tenant below
            # copies from it like any other client would.
            dataset_origins = {}
            for dataset_name, files in source.datasets.items():
                entry = dataset_library.push(
                    pack=pack.name,
                    dataset=dataset_name,
                    name="demo",
                    files=files,
                    author="command:seed_demos",
                    comment="Plantilla de la demo",
                    base_sha=None,
                ) or dataset_library.latest(pack.name, dataset_name, "demo")
                assert entry is not None
                dataset_origins[dataset_name] = dataset_library.origin(entry)
            try:
                with transaction.atomic(using="owner"):
                    store.lock()
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
                        dataset_origins=dataset_origins or None,
                        actor="command:seed_demos",
                        comment="Plantilla inicial",
                        keep_status=True,
                    )
                self.stdout.write(f"created {source.document['slug']}")
            except store.StoreError as error:
                raise archive.command_error(error) from None
