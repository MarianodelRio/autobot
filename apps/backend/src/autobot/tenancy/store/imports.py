"""Importing a whole tenant source (document, datasets, secrets) in one transaction."""

from dataclasses import replace
from typing import Any

from django.db import transaction

from autobot.tenancy.registry import TenantSource
from autobot.tenancy.store import validate
from autobot.tenancy.store.channel_secrets import secrets_for, write_secret
from autobot.tenancy.store.datasets import files_digest, latest_version, write_dataset
from autobot.tenancy.store.documents import create_tenant
from autobot.tenancy.store.errors import StoreError, identity_changed, validated_document
from autobot.tenancy.store.revision import write_document


def _write_changed_datasets(
    source: TenantSource, candidate: TenantSource, doc: dict[str, Any], *, actor: str, comment: str
) -> None:
    """A new version for each imported dataset whose content differs from the latest."""
    for name, files in source.datasets.items():
        prior = latest_version(doc["id"], name)
        if prior is None or prior.sha256 != files_digest(files):
            write_dataset(
                candidate,
                name,
                files,
                actor=actor,
                comment=comment,
                library_origin=source.dataset_origins.get(name),
            )


@transaction.atomic(using="owner")
def import_source(source: TenantSource, *, actor: str, comment: str) -> int:
    """Validate a directory's document and datasets together before publishing either."""
    revision = validate.lock()
    doc = validated_document(source.document)
    sources = validate.current_sources()
    existing = [
        s for s in sources if isinstance(s.document, dict) and s.document.get("slug") == doc["slug"]
    ]
    if not existing:
        return create_tenant(
            document=doc,
            datasets=source.datasets or None,
            dataset_origins=source.dataset_origins or None,
            secrets=source.secrets,
            actor=actor,
            comment=comment,
            keep_status=True,
        )
    current = existing[0]
    if identity_changed(doc, current.document):
        raise StoreError(
            "forbidden_change",
            "La importación no permite cambiar la identidad, el estado o el tipo de canal",
        )
    raw_secrets = secrets_for(doc, source.secrets)
    candidate = replace(
        current,
        document=doc,
        datasets={**current.datasets, **source.datasets},
        secrets=current.secrets if raw_secrets is None else raw_secrets,
        secrets_error=current.secrets_error if raw_secrets is None else None,
    )
    validate.validate_candidate(candidate, sources)
    version = write_document(
        candidate,
        revision,
        actor=actor,
        comment=comment,
        action="tenant.publish",
        summary="Configuración importada",
    )
    _write_changed_datasets(source, candidate, doc, actor=actor, comment=comment)
    if raw_secrets is not None:
        write_secret(candidate, raw_secrets, actor)
    return version
