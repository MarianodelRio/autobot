"""Tenant registry: validated documents, datasets and secrets → memory.

`load_registry` reads every tenant, validates the common part, the pack's config and the
channel secrets, loads the datasets and builds the indexes. A broken tenant never affects
the others:

- unreadable file, invalid YAML or an invalid common part: the tenant cannot be
  identified, so it is left out and reported in `Registry.errors`;
- unknown pack, invalid config, failing `load_data` or a repeated id/public_id/
  phone_number_id: the tenant is `degraded` (its contacts get the generic text);
  a repeated key also makes it `ambiguous`: it is never routed nor synced;
- missing secrets or channel ids: only its `main` channel is disabled; a demo tenant
  (no channel of its own) always has `main` disabled, without being a warning.

Messages never contain secret values.
"""

import logging
import threading
import time
from collections.abc import Iterable, Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field, replace
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

import yaml
from django.db import DatabaseError, connections, transaction
from pydantic import BaseModel, ValidationError

from autobot.tenancy.schema import SECRETS_SCHEMA, ChannelSecrets, TenantDocument
from core.pack import Pack, TenantInfo

log = logging.getLogger(__name__)

# Problems reading a file: none of them may stop the other tenants from loading.
READ_ERRORS = (OSError, UnicodeDecodeError, yaml.YAMLError)


@dataclass(frozen=True)
class LoadedTenant:
    document: TenantDocument
    version: int | None = None
    pack: Pack | None = None
    config: BaseModel | None = None
    data: object | None = None
    secrets: ChannelSecrets | None = None
    degraded: list[str] = field(default_factory=list)  # reasons; empty = healthy
    main_disabled: list[str] = field(default_factory=list)  # why the main channel is off
    ambiguous: bool = False  # shares an id/public_id/phone_number_id with another tenant

    @property
    def id(self) -> UUID:
        return self.document.id

    @property
    def slug(self) -> str:
        return self.document.slug

    @property
    def is_degraded(self) -> bool:
        return bool(self.degraded)

    @property
    def main_enabled(self) -> bool:
        return not self.main_disabled

    @property
    def is_demo(self) -> bool:
        return self.document.demo is not None

    @property
    def info(self) -> TenantInfo:
        f = self.document
        return TenantInfo(id=f.id, slug=f.slug, name=f.name, timezone=ZoneInfo(f.timezone))


@dataclass
class Registry:
    tenants: list[LoadedTenant] = field(default_factory=list)
    errors: dict[str, list[str]] = field(default_factory=dict)  # directory → problems
    by_id: dict[UUID, LoadedTenant] = field(default_factory=dict)
    by_slug: dict[str, LoadedTenant] = field(default_factory=dict)
    by_public_id: dict[tuple[str, str], LoadedTenant] = field(default_factory=dict)
    by_phone_number_id: dict[str, LoadedTenant] = field(default_factory=dict)

    def tenant(self, tenant_id: UUID) -> LoadedTenant:
        return self.by_id[tenant_id]

    def serving(self, pack: str) -> list[LoadedTenant]:
        """Tenants of `pack` that run its periodic work: not degraded nor offboarded."""
        return [
            t
            for t in self.tenants
            if t.document.pack == pack and not t.is_degraded and t.document.status != "offboarded"
        ]

    def demo_tenants(self) -> list[LoadedTenant]:
        """Demo businesses, not ambiguous. Availability (status, degraded) is the
        selector's business."""
        return [t for t in self.tenants if t.is_demo and not t.ambiguous]

    @property
    def problems(self) -> dict[str, list[str]]:
        """Unreadable documents and degraded tenants that should fail validation."""
        found = {name: list(problems) for name, problems in self.errors.items()}
        for t in self.tenants:
            if t.degraded:
                found.setdefault(t.slug, []).extend(t.degraded)
        return found


@dataclass(frozen=True)
class TenantSource:
    name: str
    document: Any
    datasets: Mapping[str, Mapping[str, str]] = field(default_factory=dict)
    secrets: Mapping[str, Any] | None = field(default=None, repr=False)
    secrets_error: str | None = None
    version: int | None = None
    document_error: str | None = None


def load_registry(sources: Iterable[TenantSource], packs: Mapping[str, Pack]) -> Registry:
    registry = Registry()
    for source in sources:
        if source.document_error:
            registry.errors[source.name] = [source.document_error]
            continue
        tenant = _load_tenant(source, packs, registry)
        if tenant is not None:
            registry.tenants.append(tenant)
    _mark_duplicates(registry)
    _index(registry)
    for name, problems in registry.problems.items():
        log.error("Tenant %s cannot serve: %s", name, "; ".join(problems))
    for t in registry.tenants:
        if t.main_disabled and not t.is_degraded and not t.is_demo:
            log.warning("Tenant %s main channel disabled: %s", t.slug, "; ".join(t.main_disabled))
    return registry


def source_from_dir(directory: Path, secrets: Mapping[str, Any] | None = None) -> TenantSource:
    document = directory / "document.yaml"
    if not document.is_file():
        document = directory / "tenant.yaml"
    if not document.is_file():
        return TenantSource(directory.name, None, document_error="no document.yaml or tenant.yaml")
    try:
        raw = yaml.safe_load(document.read_text(encoding="utf-8"))
        datasets: dict[str, dict[str, str]] = {}
        root = directory / "datasets"
        if root.is_dir():
            for dataset in sorted(root.iterdir()):
                if not dataset.is_dir():
                    continue
                files = {}
                for path in sorted(dataset.rglob("*")):
                    if path.is_symlink():
                        raise OSError("dataset symlinks are not allowed")
                    if path.is_file():
                        files[path.relative_to(dataset).as_posix()] = path.read_text(
                            encoding="utf-8"
                        )
                datasets[dataset.name] = files
        return TenantSource(directory.name, raw, datasets=datasets, secrets=secrets)
    except READ_ERRORS as error:
        return TenantSource(
            directory.name,
            None,
            document_error=f"{document.name} cannot be read ({type(error).__name__})",
        )


def sources_from_directory(root: Path, secrets_file: Path | None) -> list[TenantSource]:
    if not root.is_dir():
        log.warning("No tenants directory at %s", root)
        return []
    secrets: dict[str, Any] = {}
    secrets_error = None
    if secrets_file is not None and secrets_file.is_file():
        try:
            raw = yaml.safe_load(secrets_file.read_text(encoding="utf-8")) or {}
            if isinstance(raw, dict) and all(isinstance(key, str) for key in raw):
                secrets = raw
            else:
                secrets_error = "must map each tenant slug to its secrets"
        except READ_ERRORS as error:
            secrets_error = f"cannot be read ({type(error).__name__})"
    sources = []
    known_slugs = set()
    for path in sorted(root.iterdir()):
        if not path.is_dir():
            continue
        source = source_from_dir(path)
        slug = source.document.get("slug") if isinstance(source.document, dict) else None
        if isinstance(slug, str):
            known_slugs.add(slug)
        sources.append(
            replace(
                source,
                secrets=secrets.get(slug) if isinstance(slug, str) else None,
                secrets_error=secrets_error,
            )
        )
    unknown = sorted(set(secrets) - known_slugs)
    if unknown:
        log.warning("secrets.yaml has entries for unknown tenants: %s", ", ".join(unknown))
    return sources


def _load_tenant(
    source: TenantSource, packs: Mapping[str, Pack], registry: Registry
) -> LoadedTenant | None:
    try:
        document = TenantDocument.model_validate(source.document)
    except ValidationError as error:
        registry.errors[source.name] = _describe(error)
        return None
    tenant = LoadedTenant(document=document, version=source.version)
    tenant = _with_pack(tenant, packs, source.datasets)
    tenant = _with_secrets(tenant, source.secrets)
    if source.secrets_error and not tenant.is_demo:
        tenant = replace(
            tenant,
            secrets=None,
            main_disabled=[*tenant.main_disabled, "secrets cannot be decrypted"],
        )
    return tenant


def _dataset_path(path: str) -> bool:
    return (
        isinstance(path, str)
        and bool(path)
        and "\\" not in path
        and "\0" not in path
        and not PurePosixPath(path).is_absolute()
        and ".." not in PurePosixPath(path).parts
        and PurePosixPath(path).parts != ()
    )


def _with_pack(
    tenant: LoadedTenant, packs: Mapping[str, Pack], datasets: Mapping[str, Mapping[str, str]]
) -> LoadedTenant:
    pack = packs.get(tenant.document.pack)
    if pack is None:
        return _degrade(tenant, f"unknown pack {tenant.document.pack!r}")
    try:
        config = pack.config_schema.model_validate(tenant.document.config)
    except ValidationError as error:
        return _degrade(tenant, *(f"config: {m}" for m in _describe(error)))
    for name, files in datasets.items():
        if not _dataset_path(name) or len(PurePosixPath(name).parts) != 1:
            return _degrade(tenant, "dataset: invalid name")
        if any(
            not _dataset_path(path) or not isinstance(text, str) for path, text in files.items()
        ):
            return _degrade(tenant, f"dataset {name}: invalid path")
    data = None
    if pack.load_data is not None:
        try:
            with TemporaryDirectory(prefix="autobot-dataset-") as temporary:
                root = Path(temporary)
                for name, files in datasets.items():
                    for path, text in files.items():
                        target = root / "datasets" / name / path
                        target.parent.mkdir(parents=True, exist_ok=True)
                        target.write_text(text, encoding="utf-8")
                data = pack.load_data(tenant.info, config, root)
        except Exception as error:
            return _degrade(tenant, f"load_data failed: {type(error).__name__}: {error}")
    return replace(tenant, pack=pack, config=config, data=data)


def _with_secrets(tenant: LoadedTenant, raw: Any) -> LoadedTenant:
    channel = tenant.document.channel
    if channel is None:
        return replace(tenant, secrets=None, main_disabled=["demo tenant: no main channel"])
    disabled = [] if channel.complete else [f"{channel.type} channel ids are missing"]
    schema = SECRETS_SCHEMA[channel.type]
    secrets = None
    if raw is None:
        disabled.append("no channel secrets")
    else:
        try:
            secrets = schema.model_validate(raw)
        except ValidationError as e:
            disabled.extend(f"secrets: {m}" for m in _describe(e))
    return replace(tenant, secrets=secrets, main_disabled=disabled)


def _mark_duplicates(registry: Registry) -> None:
    def keys(t: LoadedTenant) -> Iterable[tuple[str, str]]:
        yield "id", str(t.id)
        if t.document.channel is not None:
            yield "public_id", t.document.channel.public_id
            if t.document.channel.type == "whatsapp" and t.document.channel.phone_number_id:
                yield "phone_number_id", t.document.channel.phone_number_id

    owners: dict[tuple[str, str], list[int]] = {}
    for i, t in enumerate(registry.tenants):
        for key in keys(t):
            owners.setdefault(key, []).append(i)
    for (name, _), indexes in owners.items():
        if len(indexes) > 1:
            for i in indexes:
                t = _degrade(registry.tenants[i], f"{name} repeated")
                registry.tenants[i] = replace(t, ambiguous=True)


def _index(registry: Registry) -> None:
    for t in registry.tenants:
        registry.by_slug[t.slug] = t
        if t.ambiguous:
            continue  # never routed by a key that another tenant also claims
        registry.by_id[t.id] = t
        if t.document.channel is not None:
            registry.by_public_id[(t.document.channel.type, t.document.channel.public_id)] = t
            if t.document.channel.type == "whatsapp" and t.document.channel.phone_number_id:
                registry.by_phone_number_id[t.document.channel.phone_number_id] = t


def _degrade(tenant: LoadedTenant, *reasons: str) -> LoadedTenant:
    return replace(tenant, degraded=[*tenant.degraded, *reasons])


def _describe(error: ValidationError) -> list[str]:
    """Field and message of each problem, never the input (it may hold a secret)."""
    return [f"{'.'.join(str(p) for p in e['loc']) or '(root)'}: {e['msg']}" for e in error.errors()]


def sources_from_database(alias: str = "default") -> tuple[int, list[TenantSource]]:
    """Read the current config in a single snapshot, with a bounded query count."""
    from autobot.tenancy.crypto import SecretsUnreadable, decrypt
    from autobot.tenancy.models import (
        ConfigRevision,
        TenantDatasetVersion,
        TenantDocumentVersion,
        TenantSecret,
    )

    outer_transaction = connections[alias].in_atomic_block
    with transaction.atomic(using=alias):
        if not outer_transaction:
            with connections[alias].cursor() as cursor:
                cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        revision = ConfigRevision.objects.using(alias).get(pk=1).revision
        documents = list(
            TenantDocumentVersion.objects.using(alias)
            .order_by("tenant_id", "-version")
            .distinct("tenant_id")
            .values("tenant_id", "version", "document")
        )
        datasets: dict[UUID, dict[str, dict[str, str]]] = {}
        for row in (
            TenantDatasetVersion.objects.using(alias)
            .order_by("tenant_id", "name", "-version")
            .distinct("tenant_id", "name")
            .values("tenant_id", "name", "files")
        ):
            datasets.setdefault(row["tenant_id"], {})[row["name"]] = row["files"]
        secrets = {
            row["tenant_id"]: bytes(row["ciphertext"])
            for row in TenantSecret.objects.using(alias).values("tenant_id", "ciphertext")
        }
    sources = []
    for doc_row in documents:
        document = doc_row["document"]
        tenant_id = doc_row["tenant_id"]
        raw_secrets = None
        secrets_error = None
        if tenant_id in secrets:
            try:
                raw_secrets = decrypt(secrets[tenant_id])
            except SecretsUnreadable:
                secrets_error = "secrets cannot be decrypted"
        slug = document.get("slug") if isinstance(document, dict) else None
        name = slug if isinstance(slug, str) else str(tenant_id)
        sources.append(
            TenantSource(
                name=name,
                document=document,
                datasets=datasets.get(tenant_id, {}),
                secrets=raw_secrets,
                secrets_error=secrets_error,
                version=doc_row["version"],
            )
        )
    return revision, sources


@dataclass
class _RegistryScope:
    registry: Registry | None = None


_scope: ContextVar[_RegistryScope | None] = ContextVar("registry_scope", default=None)
_registry: Registry | None = None
_revision: int | None = None
_checked_at = 0.0
_registry_lock = threading.Lock()


def reset_registry() -> None:
    """Clear the process cache, for tests and explicit operator reloads."""
    global _registry, _revision, _checked_at
    with _registry_lock:
        _registry, _revision, _checked_at = None, None, 0.0


def loaded_registry() -> Registry | None:
    """Return a loaded snapshot without I/O, including a pinned job's older snapshot."""
    scope = _scope.get()
    return scope.registry if scope is not None and scope.registry is not None else _registry


@contextmanager
def registry_scope() -> Iterator[None]:
    """Pin the first registry read for this unit of work; nested scopes reuse it."""
    if _scope.get() is not None:
        yield
        return
    token = _scope.set(_RegistryScope())
    try:
        yield
    finally:
        _scope.reset(token)


def _read_revision() -> int:
    with connections["default"].cursor() as cursor:
        cursor.execute("SELECT revision FROM config_revision WHERE id=1")
        row = cursor.fetchone()
    if row is None:
        raise DatabaseError("Configuration revision is missing")
    return int(row[0])


def _cached_registry() -> Registry:
    global _registry, _revision, _checked_at
    now = time.monotonic()
    if _registry is not None and now - _checked_at < 2:
        return _registry
    with _registry_lock:
        now = time.monotonic()
        if _registry is not None and now - _checked_at < 2:
            return _registry
        try:
            if _registry is not None and _read_revision() == _revision:
                _checked_at = now
                return _registry
            from packs.registry import PACKS

            revision, sources = sources_from_database()
            registry = load_registry(sources, PACKS)
        except DatabaseError:
            if _registry is None:
                raise
            _checked_at = now
            log.warning("Configuration reload failed; keeping the loaded registry")
            return _registry
        _registry, _revision, _checked_at = registry, revision, now
        return registry


def get_registry() -> Registry:
    scope = _scope.get()
    if scope is not None and scope.registry is not None:
        return scope.registry
    registry = _cached_registry()
    if scope is not None:
        scope.registry = registry
    return registry
