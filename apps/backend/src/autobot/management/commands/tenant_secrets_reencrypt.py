"""Rotate all channel ciphertexts atomically, using the first configured key."""

from typing import Any

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from autobot.ops.audit import record
from autobot.tenancy.crypto import SecretsUnreadable, decrypt, encrypt
from autobot.tenancy.models import TenantSecret


class Command(BaseCommand):
    help = "Reencrypt every tenant's channel secrets with the first configured Fernet key."

    def handle(self, *args: Any, **options: Any) -> None:
        count = 0
        try:
            with transaction.atomic(using="owner"):
                for secret in (
                    TenantSecret.objects.using("owner").select_for_update().order_by("pk")
                ):
                    secret.ciphertext = encrypt(decrypt(bytes(secret.ciphertext)))
                    secret.updated_by = "command:tenant_secrets_reencrypt"
                    secret.save(
                        using="owner", update_fields=["ciphertext", "updated_at", "updated_by"]
                    )
                    record(
                        actor=secret.updated_by,
                        action="tenant.secrets",
                        summary="Secretos de canal recifrados",
                        tenant_id=secret.tenant_id,
                        target_type="tenant",
                        target_id=str(secret.tenant_id),
                        details={"reencrypted": True},
                    )
                    count += 1
        except SecretsUnreadable:
            raise CommandError("Channel secrets cannot be read; rotation rolled back") from None
        self.stdout.write(f"Reencrypted {count} tenant secret(s).")
