"""`manage.py sync_tenants`: mirror tenants/*/tenant.yaml in the `tenant` table, for the
foreign keys and RLS (design.md §5.4). Run after `migrate`; idempotent. Writes as
fp_owner, since fp_app may only read that table. A broken tenant never blocks the others
nor the deploy: it is skipped and reported."""

from typing import Any

from django.core.management.base import BaseCommand
from django.db import IntegrityError, transaction
from django.utils import timezone

from flowpilot.tenancy.models import Tenant
from flowpilot.tenancy.registry import get_registry


class Command(BaseCommand):
    help = "Upsert the tenant table from tenants/*/tenant.yaml."

    def handle(self, *args: Any, **options: Any) -> None:
        registry = get_registry()
        now = timezone.now()
        for t in registry.tenants:
            f = t.file
            if t.ambiguous:  # its id may be another tenant's: never touch that row
                self.stderr.write(f"skipped {f.slug}: {'; '.join(t.degraded)}")
                continue
            try:
                with transaction.atomic(using="owner"):
                    _, created = Tenant.objects.using("owner").update_or_create(
                        id=f.id,
                        defaults={
                            "slug": f.slug,
                            "name": f.name,
                            "pack": f.pack,
                            "status": f.status,
                            "timezone": f.timezone,
                            "synced_at": now,
                        },
                    )
            except IntegrityError:  # e.g. the slug of a row with another id
                self.stderr.write(f"skipped {f.slug}: its slug belongs to another tenant id")
                continue
            state = "degraded" if t.is_degraded else f.status
            self.stdout.write(f"{'created' if created else 'updated'} {f.slug} ({state})")
        for name, problems in registry.errors.items():
            self.stderr.write(f"skipped {name}: {'; '.join(problems)}")
