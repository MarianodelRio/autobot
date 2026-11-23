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

import json
import logging
import os
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
        return TenantInfo(
            id=f.id,
            slug=f.slug,
            name=f.name,
            timezone=ZoneInfo(f.timezone),
            controller_name=f.privacy.controller_name if f.privacy else None,
            policy_url=f.privacy.policy_url if f.privacy else None,
            human_contact=f.support.human_contact if f.support else None,
        )


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
    # ADR-013: where each dataset's copy came from, {name: (entry name, version, sha256)}.
    dataset_origins: Mapping[str, tuple[str, int, str]] = field(default_factory=dict)


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


ORIGIN_SUFFIX = ".origin.json"


def _read_origin(path: Path) -> tuple[str, int, str] | None:
    """The library provenance written next to an exported dataset (ADR-013); anything
    malformed is ignored, since provenance is informative only."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        name, version, sha = raw["name"], raw["version"], raw["sha256"]
    except OSError, UnicodeError, ValueError, KeyError, TypeError:
        return None
    if isinstance(name, str) and isinstance(version, int) and isinstance(sha, str):
        return (name[:64], version, sha[:64])
    return None


def source_from_dir(directory: Path, secrets: Mapping[str, Any] | None = None) -> TenantSource:
    document = directory / "document.yaml"
    if not document.is_file():
        return TenantSource(directory.name, None, document_error="no document.yaml")
    try:
        raw = yaml.safe_load(document.read_text(encoding="utf-8"))
        datasets: dict[str, dict[str, str]] = {}
        origins: dict[str, tuple[str, int, str]] = {}
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
            for name in datasets:
                origin = _read_origin(root / f"{name}{ORIGIN_SUFFIX}")
                if origin is not None:
                    origins[name] = origin
        return TenantSource(
            directory.name, raw, datasets=datasets, secrets=secrets, dataset_origins=origins
        )
    except READ_ERRORS as error:
        return TenantSource(
            directory.name,
            None,
            document_error=f"{document.name} cannot be read ({type(error).__name__})",
        )


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


def _bad_datasets(datasets: Mapping[str, Mapping[str, str]]) -> str | None:
    """Why the datasets cannot be written to disk (an unsafe name or path), or None."""
    for name, files in datasets.items():
        if not _dataset_path(name) or len(PurePosixPath(name).parts) != 1:
            return "dataset: invalid name"
        if any(
            not _dataset_path(path) or not isinstance(text, str) for path, text in files.items()
        ):
            return f"dataset {name}: invalid path"
    return None


def _load_pack_data(
    pack: Pack, tenant: LoadedTenant, config: Any, datasets: Mapping[str, Mapping[str, str]]
) -> Any:
    """The pack's loaded data: the datasets written to a temporary directory, as its
    `load_data` reads them."""
    with TemporaryDirectory(prefix="autobot-dataset-") as temporary:
        root = Path(temporary)
        for name, files in datasets.items():
            for path, text in files.items():
                target = root / "datasets" / name / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(text, encoding="utf-8")
        assert pack.load_data is not None
        return pack.load_data(tenant.info, config, root)


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
    problem = _bad_datasets(datasets)
    if problem is not None:
        return _degrade(tenant, problem)
    data = None
    if pack.load_data is not None:
        try:
            data = _load_pack_data(pack, tenant, config, datasets)
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
        datasets, origins = _latest_datasets(TenantDatasetVersion, alias)
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
                dataset_origins=origins.get(tenant_id, {}),
            )
        )
    return revision, sources


def _latest_datasets(
    model: Any, alias: str
) -> tuple[dict[UUID, dict[str, dict[str, str]]], dict[UUID, dict[str, tuple[str, int, str]]]]:
    """The latest version of each tenant's datasets, and where each was copied from."""
    datasets: dict[UUID, dict[str, dict[str, str]]] = {}
    origins: dict[UUID, dict[str, tuple[str, int, str]]] = {}
    rows = (
        model.objects.using(alias)
        .order_by("tenant_id", "name", "-version")
        .distinct("tenant_id", "name")
        .values("tenant_id", "name", "files", "source_name", "source_version", "source_sha")
    )
    for row in rows:
        datasets.setdefault(row["tenant_id"], {})[row["name"]] = row["files"]
        if row["source_name"] and row["source_version"] is not None and row["source_sha"]:
            origins.setdefault(row["tenant_id"], {})[row["name"]] = (
                row["source_name"],
                row["source_version"],
                row["source_sha"],
            )
    return datasets, origins


@dataclass
class _RegistryScope:
    registry: Registry | None = None


_scope: ContextVar[_RegistryScope | None] = ContextVar("registry_scope", default=None)
_registry: Registry | None = None
_revision: int | None = None
_checked_at = 0.0
_registry_lock = threading.Lock()  # held while checking the revision and rebuilding
# The background refresher: ONE persistent daemon thread per process, started lazily. It
# sleeps on `_refresh_wanted` and keeps its own Django connection between checks (so the
# web does not connect/authenticate/close every 2 s window); it closes it only when a
# check failed or the connection is unusable/obsolete. `_refresh_state` (under
# `_refresh_cv`) is "idle", "queued" (requested, not started) or "running".
_refresh_cv = threading.Condition()
_refresh_state = "idle"
_refresher: threading.Thread | None = None
_refresher_pid = 0
_last_reload_ok = True


def _after_fork_in_child() -> None:
    """A forked process (gunicorn with `--preload`, a worker) has none of the parent's
    threads, and may have inherited a lock held by one: start over with fresh primitives,
    keeping the loaded snapshot."""
    global _registry_lock, _refresh_cv, _refresh_state, _refresher, _refresher_pid
    _registry_lock = threading.Lock()
    _refresh_cv = threading.Condition()
    _refresh_state = "idle"
    _refresher, _refresher_pid = None, 0


os.register_at_fork(after_in_child=_after_fork_in_child)


def reset_registry() -> None:
    """Clear the process cache, for tests and explicit operator reloads."""
    global _registry, _revision, _checked_at
    wait_for_refresh()
    with _registry_lock:
        _registry, _revision, _checked_at = None, None, 0.0


def wait_for_refresh(timeout: float | None = 30) -> None:
    """Wait for the background rebuild queued or in flight, if any (tests, shutdown)."""
    with _refresh_cv:
        _refresh_cv.wait_for(lambda: _refresh_state == "idle", timeout)


def warm_up() -> None:
    """Load the registry now, so the first request or job does not pay for it.

    Never raises: if the database is not reachable the first caller retries and
    reports the error as before."""
    try:
        get_registry()
    except Exception:
        log.warning("Registry warm-up failed; the first caller will load it")
    finally:
        connections.close_all()


def warm_up_in_background() -> None:
    """`warm_up` on a daemon thread, for process boot that must not wait for it."""
    threading.Thread(target=warm_up, name="registry-warm-up", daemon=True).start()


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


def _reload_locked(now: float) -> Registry:
    """Check the revision and rebuild if it changed. Needs `_registry_lock`.

    The new snapshot is published only once complete; if the rebuild fails the
    previous one stays (the first load propagates the error)."""
    global _registry, _revision, _checked_at, _last_reload_ok
    _last_reload_ok = False
    try:
        if _registry is not None and _read_revision() == _revision:
            _checked_at = now
            _last_reload_ok = True
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
    except Exception:
        if _registry is None:
            raise
        _checked_at = now
        log.exception("Configuration rebuild failed; keeping the loaded registry")
        return _registry
    _registry, _revision, _checked_at = registry, revision, now
    _last_reload_ok = True
    return registry


def _is_queued() -> bool:
    return _refresh_state == "queued"


def _refresher_loop(cv: threading.Condition) -> None:
    """The refresher thread: one check/rebuild per request, on its own connection."""
    global _refresh_state
    connection = connections["default"]
    while True:
        with cv:
            cv.wait_for(_is_queued)
            _refresh_state = "running"
        try:
            connection.close_if_unusable_or_obsolete()
            connection.close_if_health_check_failed()
        except Exception:
            # The kept connection is broken (or cannot even be checked): drop it and
            # still try the reload, which opens a fresh one, rather than skip this round.
            connections.close_all()
        try:
            with _registry_lock:
                _reload_locked(time.monotonic())
                ok = _last_reload_ok
        except Exception:
            log.exception("Registry refresher failed")
            ok = False
        if not ok:
            connections.close_all()  # never keep a connection that just failed
        with cv:
            _refresh_state = "idle"
            cv.notify_all()


def _request_refresh() -> None:
    """Ask the refresher for one check, unless one is queued or running."""
    global _refresher, _refresher_pid, _refresh_state
    with _refresh_cv:
        if _refresh_state != "idle":
            return
        if _refresher is None or _refresher_pid != os.getpid() or not _refresher.is_alive():
            thread = threading.Thread(
                target=_refresher_loop, args=(_refresh_cv,), name="registry-refresh", daemon=True
            )
            try:
                thread.start()  # cannot start a thread: serve the old snapshot
            except RuntimeError:
                return
            _refresher, _refresher_pid = thread, os.getpid()
        _refresh_state = "queued"
        _refresh_cv.notify_all()


def _cached_registry(*, force: bool = False) -> Registry:
    """Stale-while-revalidate. Within 2 s of the last check the loaded snapshot is
    returned. After that, the first caller wakes the process's single refresher thread,
    which checks the revision and rebuilds if it changed; everyone keeps using the
    previous snapshot until the new one is swapped in, so no request or job waits for a
    rebuild (3.8 s at 300 tenants, 40 s at 3,000).

    Synchronous (blocking) paths: the very first load, and `force`, which skips the
    window and re-checks the revision now. Callers that need fresh config right after
    a write (just-created tenant not found, panel services) use `force`: with several
    gunicorn workers this process's own cache may be behind the write."""
    global _checked_at
    now = time.monotonic()
    current = _registry
    if not force and current is not None and now - _checked_at < 2:
        return current
    if not force and current is not None:
        _checked_at = now  # one check per window, whatever the rebuild takes
        _request_refresh()
        return current
    with _registry_lock:
        now = time.monotonic()
        if not force and _registry is not None and now - _checked_at < 2:
            return _registry
        return _reload_locked(now)


def get_registry(*, force: bool = False) -> Registry:
    scope = _scope.get()
    if scope is not None and scope.registry is not None and not force:
        return scope.registry
    registry = _cached_registry(force=force)
    if scope is not None:
        scope.registry = registry
    return registry
