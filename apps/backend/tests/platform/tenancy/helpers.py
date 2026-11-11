"""Builders of tenants/ and secrets.yaml trees for the registry tests."""

import uuid
from pathlib import Path
from typing import Any

import yaml

from tests.fixtures.toy_pack import pack as toy

PACKS = {"toy": toy.pack}
WA_SECRETS = {
    "app_secret": "S3CR3T-APP-" + "x" * 21,
    "access_token": "EAAB-T0KEN",
    "verify_token": "V3RIFY-T0KEN",
}
TG_SECRETS = {"bot_token": "123:ABC-token", "webhook_secret": "w" * 32}


def phone_number_id(slug: str) -> str:
    """A numeric Meta id, different for each slug."""
    return str(int.from_bytes(slug.encode()) % 10**15)


def tenant_yaml(slug: str, **changes: Any) -> dict[str, Any]:
    doc: dict[str, Any] = {
        "id": str(uuid.uuid7()),
        "slug": slug,
        "name": slug.title(),
        "status": "active",
        "timezone": "Europe/Madrid",
        "pack": "toy",
        "channel": {
            "type": "whatsapp",
            "public_id": f"pub{slug.replace('-', '')}0000"[:16],
            "app_id": "1",
            "waba_id": "2",
            "phone_number_id": phone_number_id(slug),
        },
        "testers": {"main": ["34600000001"]},
        "config": {},
    }
    doc.update(changes)
    return doc


def demo_tenant_yaml(slug: str, **changes: Any) -> dict[str, Any]:
    doc: dict[str, Any] = {
        "id": str(uuid.uuid7()),
        "slug": slug,
        "name": slug.title(),
        "status": "active",
        "timezone": "Europe/Madrid",
        "pack": "toy",
        "demo": {"description": "Demo"},
        "config": {},
    }
    doc.update(changes)
    return doc


def write_tenants(root: Path, *docs: dict[str, Any], raw: dict[str, str] | None = None) -> Path:
    tenants = root / "tenants"
    tenants.mkdir(exist_ok=True)
    for doc in docs:
        (tenants / doc["slug"]).mkdir()
        (tenants / doc["slug"] / "tenant.yaml").write_text(yaml.safe_dump(doc))
    for name, text in (raw or {}).items():
        (tenants / name).mkdir()
        (tenants / name / "tenant.yaml").write_text(text)
    return tenants


def write_secrets(root: Path, secrets: dict[str, Any]) -> Path:
    path = root / "secrets.yaml"
    path.write_text(yaml.safe_dump(secrets))
    return path


def seed_db(
    *docs: dict[str, Any],
    secrets: dict[str, Any] | None = None,
    datasets: dict[str, dict[str, dict[str, str]]] | None = None,
) -> None:
    """Publish test configuration directly, without depending on operator services."""
    import hashlib
    import json

    from django.db import transaction
    from django.utils import timezone

    from autobot.tenancy.crypto import encrypt
    from autobot.tenancy.models import (
        ConfigRevision,
        Tenant,
        TenantDatasetVersion,
        TenantDocumentVersion,
        TenantSecret,
    )
    from autobot.tenancy.registry import reset_registry

    with transaction.atomic(using="owner"):
        revision, _ = ConfigRevision.objects.using("owner").get_or_create(pk=1)
        for doc in docs:
            tenant, _ = Tenant.objects.using("owner").update_or_create(
                pk=doc["id"],
                defaults={
                    "slug": doc["slug"],
                    "name": doc["name"],
                    "pack": doc["pack"],
                    "status": doc["status"],
                    "timezone": doc["timezone"],
                    "synced_at": timezone.now(),
                },
            )
            previous = (
                TenantDocumentVersion.objects.using("owner")
                .filter(
                    tenant=tenant,
                )
                .order_by("-version")
                .first()
            )
            TenantDocumentVersion.objects.using("owner").create(
                tenant=tenant,
                document=doc,
                version=previous.version + 1 if previous else 1,
                author="test",
                comment="test fixture",
            )
            if secrets is not None and doc["slug"] in secrets and doc.get("channel"):
                TenantSecret.objects.using("owner").update_or_create(
                    tenant=tenant,
                    defaults={
                        "channel_type": doc["channel"]["type"],
                        "ciphertext": encrypt(secrets[doc["slug"]]),
                        "updated_by": "test",
                    },
                )
            for name, files in (datasets or {}).get(doc["slug"], {}).items():
                prior = (
                    TenantDatasetVersion.objects.using("owner")
                    .filter(
                        tenant=tenant,
                        name=name,
                    )
                    .order_by("-version")
                    .first()
                )
                TenantDatasetVersion.objects.using("owner").create(
                    tenant=tenant,
                    name=name,
                    files=files,
                    version=prior.version + 1 if prior else 1,
                    sha256=hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest(),
                    author="test",
                    comment="test fixture",
                )
        revision.revision += 1
        revision.save(using="owner")
    reset_registry()
