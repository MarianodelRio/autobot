"""A tenant's channel secrets: validation, encrypted storage and replacement."""

from collections.abc import Mapping
from dataclasses import replace
from typing import Any

from django.db import transaction
from pydantic import ValidationError

from autobot.ops import audit
from autobot.tenancy.crypto import encrypt
from autobot.tenancy.models import TenantSecret
from autobot.tenancy.registry import TenantSource
from autobot.tenancy.schema import SECRETS_SCHEMA, TenantDocument
from autobot.tenancy.store import validate
from autobot.tenancy.store.errors import StoreError, validated_document, validation_error
from autobot.tenancy.store.revision import bump

NO_SECRETS_FOR_DEMO = "Un demo no admite secretos de canal"


def _validated(channel_type: str, raw: Mapping[str, str]) -> dict[str, str]:
    try:
        validated = SECRETS_SCHEMA[channel_type].model_validate(raw)
    except ValidationError as error:
        raise validation_error(error, "secrets.") from None
    return {key: value.get_secret_value() for key, value in validated.model_dump().items()}


def secrets_for(
    document: Mapping[str, Any], raw: Mapping[str, str] | None
) -> dict[str, str] | None:
    """The validated secrets for this validated document, None if there are none; a demo
    (no channel) admits none."""
    if raw is None:
        return None
    channel = document.get("channel")
    if channel is None:
        raise StoreError("bad_request", NO_SECRETS_FOR_DEMO)
    return _validated(channel["type"], raw)


def write_secret(source: TenantSource, raw: Mapping[str, str], actor: str) -> None:
    doc = source.document
    TenantSecret.objects.using("owner").update_or_create(
        tenant_id=doc["id"],
        defaults={
            "channel_type": doc["channel"]["type"],
            "ciphertext": encrypt(raw),
            "updated_by": actor,
        },
    )
    audit.record_tenant(
        actor,
        "tenant.secrets",
        TenantDocument.model_validate(doc).id,
        "Secretos de canal sustituidos",
        fields=sorted(raw),
    )


@transaction.atomic(using="owner")
def set_secrets(slug: str, *, secrets: Mapping[str, str], actor: str) -> None:
    revision = validate.lock()
    sources = validate.current_sources()
    current = validate.find_source(slug, sources)
    channel = validated_document(current.document).get("channel")
    if channel is None or current.document.get("demo") is not None:
        raise StoreError("bad_request", NO_SECRETS_FOR_DEMO)
    # Partial substitution: blank (or whitespace-only) or absent fields keep
    # the currently readable secrets. If a field is missing from both, validation
    # below rejects it.
    provided = {name: value.strip() for name, value in secrets.items() if value.strip()}
    merged = {**(current.secrets or {}), **provided}
    raw = _validated(channel["type"], merged)
    candidate = replace(current, secrets=raw, secrets_error=None)
    validate.validate_candidate(candidate, sources)
    write_secret(candidate, raw, actor)
    bump(revision)
