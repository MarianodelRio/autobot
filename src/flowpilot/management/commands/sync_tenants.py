"""`manage.py sync_tenants`: mirror tenants/*/tenant.yaml in the `tenant` table, for the
foreign keys and RLS (design.md §5.4). Run after `migrate`; idempotent. Writes as
fp_owner, since fp_app may only read that table. A broken tenant never blocks the others
nor the deploy: it is skipped and reported."""

from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import IntegrityError, transaction
from django.utils import timezone

from flowpilot.tenancy.models import Tenant
from flowpilot.tenancy.registry import get_registry


class Command(BaseCommand):
    help = "Upsert the tenant table from tenants/*/tenant.yaml."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--strict", action="store_true", help="Fail if any tenant is skipped")

    def handle(self, *args: Any, **options: Any) -> None:
        registry = get_registry()
        now = timezone.now()
        skipped = False
        for t in registry.tenants:
            f = t.file
            if t.ambiguous:  # its id may be another tenant's: never touch that row
                self.stderr.write(f"skipped {f.slug}: {'; '.join(t.degraded)}")
                skipped = True
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
                skipped = True
                continue
            state = "degraded" if t.is_degraded else f.status
            self.stdout.write(f"{'created' if created else 'updated'} {f.slug} ({state})")
        for name, problems in registry.errors.items():
            self.stderr.write(f"skipped {name}: {'; '.join(problems)}")
            skipped = True
        if options["strict"] and skipped:
            raise CommandError("Some tenants could not be synchronized")
