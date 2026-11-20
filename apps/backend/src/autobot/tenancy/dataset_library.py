"""Dataset library (ADR-013): named, versioned datasets independent of any tenant,
uploaded by terminal and copied (never referenced) into a tenant's own
`TenantDatasetVersion` when chosen at onboarding or applied from its ficha.
"""

import hashlib
import json
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid7

from django.db import IntegrityError, connections, transaction

from autobot.ops.audit import record
from autobot.tenancy.models import DatasetLibraryVersion


class LibraryError(Exception):
    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


def digest(files: Mapping[str, str]) -> str:
    return hashlib.sha256(json.dumps(dict(files), sort_keys=True).encode()).hexdigest()


def latest(pack: str, dataset: str, name: str) -> DatasetLibraryVersion | None:
    return (
        DatasetLibraryVersion.objects.using("owner")
        .filter(pack=pack, dataset=dataset, name=name)
        .order_by("-version")
        .first()
    )


def get(pack: str, dataset: str, name: str, version: int | None = None) -> DatasetLibraryVersion:
    qs = DatasetLibraryVersion.objects.using("owner").filter(pack=pack, dataset=dataset, name=name)
    entry = (
        qs.filter(version=version).first()
        if version is not None
        else qs.order_by("-version").first()
    )
    if entry is None:
        raise LibraryError("No se encuentra esa entrada de la biblioteca")
    return entry


def list_entries(pack: str, dataset: str) -> list[DatasetLibraryVersion]:
    """The latest version of each distinctly named entry for a pack's dataset,
    ordered by name."""
    return list(
        DatasetLibraryVersion.objects.using("owner")
        .filter(pack=pack, dataset=dataset)
        .order_by("name", "-version")
        .distinct("name")
    )


def _summarize(pack_obj: object, dataset: str, files: Mapping[str, str]) -> dict[str, object]:
    from core.pack import Pack

    assert isinstance(pack_obj, Pack)
    if pack_obj.dataset_summary is None:
        raise LibraryError(f"El pack {pack_obj.name!r} no declara datasets.")
    with tempfile.TemporaryDirectory(prefix="autobot-dataset-") as tmp:
        root = Path(tmp)
        for relpath, content in files.items():
            target = root / relpath
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        try:
            return pack_obj.dataset_summary(dataset, root)
        except Exception as error:
            raise LibraryError(f"{type(error).__name__}: {error}") from None


@transaction.atomic(using="owner")
def push(
    *,
    pack: str,
    dataset: str,
    name: str,
    files: Mapping[str, str],
    author: str,
    comment: str,
    base_sha: str | None,
) -> DatasetLibraryVersion | None:
    """Validates `files` with the pack's own `dataset_summary` and creates a new
    version. Returns `None`, creating nothing, when the content is byte-identical to
    the current version. Raises `LibraryError` if `base_sha` is given and does not
    match the current version (someone else's upload landed first) or the pack
    rejects the content."""
    from packs.registry import PACKS

    pack_obj = PACKS.get(pack)
    if pack_obj is None:
        raise LibraryError(f"No se encuentra el pack {pack!r}")
    # Serialize concurrent uploads of the same entry: without it two pushes both read
    # the same `prior` and the loser dies on the unique constraint.
    with connections["owner"].cursor() as cursor:
        cursor.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
            [f"dataset_library:{pack}/{dataset}/{name}"],
        )
    prior = latest(pack, dataset, name)
    new_digest = digest(files)
    if prior is not None:
        if base_sha is not None and prior.sha256 != base_sha:
            raise LibraryError("Hay una versión más reciente; vuelve a bajarla primero.")
        if prior.sha256 == new_digest:
            return None
    summary = _summarize(pack_obj, dataset, files)
    version = (prior.version + 1) if prior else 1
    try:
        with transaction.atomic(using="owner"):
            entry = DatasetLibraryVersion.objects.using("owner").create(
                id=uuid7(),
                pack=pack,
                dataset=dataset,
                name=name,
                version=version,
                files=dict(files),
                sha256=new_digest,
                summary=summary,
                author=author,
                comment=comment,
            )
    except IntegrityError:
        raise LibraryError("Hay una versión más reciente; vuelve a bajarla primero.") from None
    record(
        actor=author,
        action="dataset_library.push",
        target_type="dataset_library",
        target_id=f"{pack}/{dataset}/{name}",
        summary="Conjunto de datos subido a la biblioteca",
        details={"version": version, "comment": comment},
    )
    return entry


@dataclass(frozen=True)
class DiffResult:
    base_sha: str | None
    new_sha: str
    changed: bool


def origin(entry: DatasetLibraryVersion) -> tuple[str, int, str]:
    """What a tenant's own copy of this entry records (ADR-013): never a live
    reference, just where it came from."""
    return (entry.name, entry.version, entry.sha256)


def apply_to_tenant(
    slug: str,
    dataset: str,
    *,
    pack: str,
    name: str,
    version: int | None,
    actor: str,
    comment: str,
) -> int | None:
    """Copies a library entry's files into the tenant's own dataset (C23's
    "Aplicar"). `None` when the tenant already has this exact content."""
    from autobot.tenancy import store

    entry = get(pack, dataset, name, version)
    return store.import_dataset(
        slug,
        dataset,
        entry.files,
        actor=actor,
        comment=comment or f"Aplicado de la biblioteca: {name} v{entry.version}",
        library_origin=origin(entry),
    )


def preview(*, pack: str, dataset: str, name: str, files: Mapping[str, str]) -> DiffResult:
    """A dry run (C21's `--dry-run`): validates and reports whether this would
    create a new version, without writing anything."""
    from packs.registry import PACKS

    pack_obj = PACKS.get(pack)
    if pack_obj is None:
        raise LibraryError(f"No se encuentra el pack {pack!r}")
    _summarize(pack_obj, dataset, files)
    prior = latest(pack, dataset, name)
    new_digest = digest(files)
    return DiffResult(
        base_sha=prior.sha256 if prior else None,
        new_sha=new_digest,
        changed=prior is None or prior.sha256 != new_digest,
    )
