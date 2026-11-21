"""A tenant's own dataset versions (copies, never references, of a library entry)."""

from collections.abc import Mapping
from dataclasses import replace
from uuid import UUID

from django.db import transaction

from autobot.ops import audit
from autobot.tenancy.dataset_library import digest
from autobot.tenancy.models import TenantDatasetVersion
from autobot.tenancy.registry import TenantSource
from autobot.tenancy.schema import TenantDocument
from autobot.tenancy.store import validate
from autobot.tenancy.store.errors import StoreError
from autobot.tenancy.store.revision import bump

type LibraryOrigin = tuple[str, int, str]  # (name, version, sha256) of the library entry


def files_digest(files: Mapping[str, str]) -> str:
    if any(not isinstance(path, str) or not isinstance(text, str) for path, text in files.items()):
        raise StoreError(
            "validation_error", "Dataset no válido", ["datasets: solo se admite texto UTF-8"]
        )
    return digest(files)


def latest_version(tenant_id: UUID | str, name: str) -> TenantDatasetVersion | None:
    return (
        TenantDatasetVersion.objects.using("owner")
        .filter(tenant_id=tenant_id, name=name)
        .order_by("-version")
        .first()
    )


def write_dataset(
    source: TenantSource,
    name: str,
    files: Mapping[str, str],
    *,
    actor: str,
    comment: str,
    library_origin: LibraryOrigin | None = None,
) -> int:
    tenant_id = source.document["id"]
    prior = latest_version(tenant_id, name)
    version = prior.version + 1 if prior else 1
    source_name, source_version, source_sha = library_origin or (None, None, None)
    TenantDatasetVersion.objects.using("owner").create(
        tenant_id=tenant_id,
        name=name,
        files=dict(files),
        version=version,
        sha256=files_digest(files),
        author=actor,
        comment=comment,
        source_name=source_name,
        source_version=source_version,
        source_sha=source_sha,
    )
    audit.record(
        actor=actor,
        action="dataset.import",
        tenant_id=TenantDocument.model_validate(source.document).id,
        target_type="dataset",
        target_id=f"{tenant_id}:{name}",
        summary="Dataset importado",
        details={"name": name, "version": version, "comment": comment},
    )
    return version


@transaction.atomic(using="owner")
def import_dataset(
    slug: str,
    name: str,
    files: Mapping[str, str],
    *,
    actor: str,
    comment: str,
    library_origin: LibraryOrigin | None = None,
) -> int | None:
    revision = validate.lock()
    sources = validate.current_sources()
    current = validate.find_source(slug, sources)
    new_digest = files_digest(files)
    previous = latest_version(current.document["id"], name)
    if previous is not None and previous.sha256 == new_digest:
        return None
    candidate = replace(current, datasets={**current.datasets, name: files})
    validate.validate_candidate(candidate, sources)
    version = write_dataset(
        candidate, name, files, actor=actor, comment=comment, library_origin=library_origin
    )
    bump(revision)
    return version
