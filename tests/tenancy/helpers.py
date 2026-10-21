"""Builders of tenants/ and secrets.yaml trees for the registry tests."""

import uuid
from pathlib import Path
from typing import Any

import yaml

from tests.toy_pack import pack as toy

PACKS = {"toy": toy.pack}
WA_SECRETS = {
    "app_secret": "S3CR3T-APP",
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
        "testers": {"telegram": [111], "main": ["34600000001"]},
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
