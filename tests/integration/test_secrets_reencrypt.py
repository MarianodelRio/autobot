"""A failed rotation rolls back ciphertexts and audit events together."""

from io import StringIO
from uuid import uuid7

import pytest
from cryptography.fernet import Fernet
from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils import timezone
from pytest_django import Settings

from autobot.ops.models import AuditEvent
from autobot.tenancy.crypto import decrypt, encrypt
from autobot.tenancy.models import Tenant, TenantSecret

pytestmark = pytest.mark.django_db(transaction=True, databases=["default", "owner"])


def create_secret(slug: str, ciphertext: bytes) -> TenantSecret:
    tenant = Tenant.objects.using("owner").create(
        id=uuid7(),
        slug=slug,
        name=slug,
        pack="toy",
        status="active",
        timezone="UTC",
        synced_at=timezone.now(),
    )
    return TenantSecret.objects.using("owner").create(
        tenant=tenant,
        channel_type="telegram",
        ciphertext=ciphertext,
        updated_by="test",
    )


def test_command_rotates_and_audits(settings: Settings) -> None:
    a, b = (Fernet.generate_key().decode() for _ in range(2))
    settings.SECRETS_ENCRYPTION_KEYS = [a]
    secret = create_secret("a", encrypt({"bot_token": "private"}))
    settings.SECRETS_ENCRYPTION_KEYS = [b, a]
    call_command("tenant_secrets_reencrypt", stdout=StringIO())
    secret.refresh_from_db(using="owner")
    settings.SECRETS_ENCRYPTION_KEYS = [b]
    assert decrypt(bytes(secret.ciphertext)) == {"bot_token": "private"}
    event = AuditEvent.objects.using("owner").get(tenant_id=secret.tenant_id)
    assert event.action == "tenant.secrets"
    assert event.details == {"reencrypted": True}
    assert event.actor == secret.updated_by == "command:tenant_secrets_reencrypt"


def test_command_failure_rolls_back_everything() -> None:
    token = encrypt({"bot_token": "private"})
    first = create_secret("first", token)
    create_secret("second", b"invalid-private-token")
    with pytest.raises(CommandError, match="rotation rolled back") as error:
        call_command("tenant_secrets_reencrypt", stdout=StringIO())
    assert "invalid-private-token" not in str(error.value)
    first.refresh_from_db(using="owner")
    assert bytes(first.ciphertext) == token
    assert first.updated_by == "test"
    assert not AuditEvent.objects.using("owner").exists()
