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

import atexit
import json
import logging
import os
import socket
import threading
import time
from collections.abc import Callable, Iterable, Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

import yaml
from django.db import DatabaseError, connections, transaction
from django.db.models.functions import MD5
from django.utils import timezone
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
            policy_url=f.privacy.policy_url if f.privacy else None,
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
    tenant_id: UUID | None = None  # set when it comes from the database


def load_registry(sources: Iterable[TenantSource], packs: Mapping[str, Pack]) -> Registry:
    """A registry from `sources`, in their order, loading every one of them."""
    return _assemble(_load_entry(source, packs) for source in sources)


@dataclass(frozen=True)
class _Entry:
    """What loading one source gave, BEFORE the passes that look across tenants: either
    the tenant, or why it was left out. Immutable and shared between the snapshots of a
    process, so an unchanged tenant is loaded once (`_reload_locked`)."""

    name: str
    tenant: LoadedTenant | None = None
    errors: tuple[str, ...] = ()
    fingerprint: Any = None


def _load_entry(source: TenantSource, packs: Mapping[str, Pack], fingerprint: Any = None) -> _Entry:
    if source.document_error:
        return _Entry(source.name, errors=(source.document_error,), fingerprint=fingerprint)
    tenant, errors = _load_tenant(source, packs)
    return _Entry(source.name, tenant, tuple(errors), fingerprint)


def _assemble(entries: Iterable[_Entry]) -> Registry:
    """The registry of `entries` (in order): the passes across tenants run on fresh lists,
    never on the cached entries, so a duplicate never leaves a mark on them."""
    registry = Registry()
    for entry in entries:
        if entry.tenant is None:
            registry.errors[entry.name] = list(entry.errors)
        else:
            registry.tenants.append(entry.tenant)
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
    source: TenantSource, packs: Mapping[str, Pack]
) -> tuple[LoadedTenant | None, list[str]]:
    """The tenant of `source`, or why it cannot be identified."""
    try:
        document = TenantDocument.model_validate(source.document)
    except ValidationError as error:
        return None, _describe(error)
    tenant = LoadedTenant(document=document, version=source.version)
    tenant = _with_pack(tenant, packs, source.datasets)
    tenant = _with_secrets(tenant, source.secrets)
    if source.secrets_error and not tenant.is_demo:
        tenant = replace(
            tenant,
            secrets=None,
            main_disabled=[*tenant.main_disabled, "secrets cannot be decrypted"],
        )
    return tenant, []


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


Fingerprint = tuple[Any, ...]


@dataclass(frozen=True)
class ConfigRead:
    """One snapshot of the configuration: its revision, the fingerprint of every tenant
    (None when not asked for) and the sources read in full, which are every tenant or,
    given `known` fingerprints, only the new and the changed ones."""

    revision: int
    fingerprints: dict[UUID, Fingerprint] | None
    sources: list[TenantSource]


def sources_from_database(alias: str = "default") -> tuple[int, list[TenantSource]]:
    """Read the current config in a single snapshot, with a bounded query count."""
    read = read_config(alias, fingerprints=False)
    return read.revision, read.sources


def read_config(
    alias: str = "default",
    known: Mapping[UUID, Fingerprint] | None = None,
    *,
    fingerprints: bool = True,
) -> ConfigRead:
    """The config in ONE read-only REPEATABLE READ snapshot, with a bounded query count.

    With `known` (the fingerprints of what the caller already holds) only the tenants
    whose fingerprint differs, or that it lacks, are read in full; the rest cost three
    aggregate queries that carry no payload."""
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
        current = _fingerprints(alias) if fingerprints or known is not None else None
        wanted: set[UUID] | None = None  # None: every tenant
        if known is not None and current is not None:
            wanted = {tid for tid, fp in current.items() if known.get(tid) != fp}
        if wanted is not None and not wanted:
            documents: list[Any] = []
            datasets: dict[UUID, dict[str, dict[str, str]]] = {}
            origins: dict[UUID, dict[str, tuple[str, int, str]]] = {}
            secrets: dict[UUID, bytes] = {}
        else:
            doc_rows = TenantDocumentVersion.objects.using(alias)
            secret_rows = TenantSecret.objects.using(alias)
            if wanted is not None:
                doc_rows = doc_rows.filter(tenant_id__in=wanted)
                secret_rows = secret_rows.filter(tenant_id__in=wanted)
            documents = list(
                doc_rows.order_by("tenant_id", "-version")
                .distinct("tenant_id")
                .values("tenant_id", "version", "document")
            )
            datasets, origins = _latest_datasets(TenantDatasetVersion, alias, wanted)
            secrets = {
                row["tenant_id"]: bytes(row["ciphertext"])
                for row in secret_rows.values("tenant_id", "ciphertext")
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
                tenant_id=tenant_id,
            )
        )
    return ConfigRead(revision, current if fingerprints else None, sources)


def _fingerprints(alias: str) -> dict[UUID, Fingerprint]:
    """What identifies the content of each tenant without reading it: the row of its
    latest document, of the latest version of each dataset and its secrets' row and hash.
    Row ids grow with every write, so a tenant purged and created again never repeats one;
    three queries, no payload."""
    from autobot.tenancy.models import TenantDatasetVersion, TenantDocumentVersion, TenantSecret

    documents = {
        tenant_id: (version, row_id)
        for tenant_id, version, row_id in TenantDocumentVersion.objects.using(alias)
        .order_by("tenant_id", "-version")
        .distinct("tenant_id")
        .values_list("tenant_id", "version", "id")
    }
    datasets: dict[UUID, list[tuple[str, int, int]]] = {}
    for tenant_id, name, version, row_id in (
        TenantDatasetVersion.objects.using(alias)
        .order_by("tenant_id", "name", "-version")
        .distinct("tenant_id", "name")
        .values_list("tenant_id", "name", "version", "id")
    ):
        datasets.setdefault(tenant_id, []).append((name, version, row_id))
    secrets = {
        tenant_id: (updated_at, digest)
        for tenant_id, updated_at, digest in TenantSecret.objects.using(alias)
        .annotate(digest=MD5("ciphertext"))
        .values_list("tenant_id", "updated_at", "digest")
    }
    return {
        tenant_id: (document, tuple(sorted(datasets.get(tenant_id, ()))), secrets.get(tenant_id))
        for tenant_id, document in documents.items()
    }


def _latest_datasets(
    model: Any, alias: str, only: set[UUID] | None = None
) -> tuple[dict[UUID, dict[str, dict[str, str]]], dict[UUID, dict[str, tuple[str, int, str]]]]:
    """The latest version of each tenant's datasets (of the tenants in `only`, if given),
    and where each was copied from."""
    datasets: dict[UUID, dict[str, dict[str, str]]] = {}
    origins: dict[UUID, dict[str, tuple[str, int, str]]] = {}
    query = model.objects.using(alias)
    if only is not None:
        query = query.filter(tenant_id__in=only)
    rows = (
        query.order_by("tenant_id", "name", "-version")
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


# Seconds between two revision checks of the polling refresher, and the window inside
# which a hot-path caller does not even wake it (ADR-030).
POLL_SECONDS = 2.0
# At most one check per this many seconds, process and bucket, for lookup misses.
MISS_RETRY_SECONDS = 1.0
# The longest a lookup miss waits for the refresher to publish a newer snapshot, or for
# the check another miss of its bucket has in flight. Never longer, whatever the rebuild.
MISS_WAIT_SECONDS = 1.0
# A polling process tells the database which revision it has loaded (`config_follower`):
# at once when it changes, and otherwise at most this often, so it counts as alive.
HEARTBEAT_SECONDS = 15.0
# While a failure repeats, it is logged at most this often.
FAILURE_LOG_SECONDS = 60.0

_scope: ContextVar[_RegistryScope | None] = ContextVar("registry_scope", default=None)
_registry: Registry | None = None
_revision: int | None = None
# What `_registry` was built from: the loaded entry of each tenant, by tenant id. Only
# touched under `_registry_lock`, and replaced as a whole together with `_registry`.
_entries: dict[UUID, _Entry] | None = None
_checked_at = 0.0
_registry_lock = threading.Lock()  # held while checking the revision and rebuilding
# The background refresher: ONE persistent daemon thread per process, started lazily (or
# by `start_polling`). It sleeps on `_refresh_cv` until a caller queues a check; once
# polling is on it also wakes by itself every `_poll_interval` seconds, so a process that
# nobody calls still follows the configuration. In polling mode it keeps its own Django
# connection between checks and drops it only after a failed check; otherwise it follows
# Django's `CONN_MAX_AGE` rules. `_refresh_state` (under `_refresh_cv`) is "idle",
# "queued" (requested, not started) or "running"; a request made while it runs sets
# `_rerun`, so one more check follows it. `_stop_target` is the thread `stop_polling` is
# stopping: it alone obeys, and a request made meanwhile starts another thread.
_refresh_cv = threading.Condition()
_refresh_state = "idle"
_rerun = False
_refresher: threading.Thread | None = None
_refresher_pid = 0
_poll_interval: float | None = None
_stop_target: threading.Thread | None = None
_last_reload_ok = True
# The heartbeat (`_beat`), touched only by the refresher thread: what was last written
# (revision, in error), when (monotonic), and the earliest next attempt after a failure.
# `_error_since` is when the current run of failed checks began.
_beat_key: tuple[int, bool] | None = None
_beat_at = float("-inf")
_beat_retry_at = float("-inf")
_error_since: datetime | None = None
_polling_started_at: datetime | None = None
_atexit_registered = False
_last_logged: dict[str, float] = {}


class _Bucket:
    """The throttle of one kind of lookup miss: when it last checked, and the check in
    flight (an event the others can wait for)."""

    def __init__(self) -> None:
        self.last = float("-inf")
        self.inflight: threading.Event | None = None


# Public lookups (`tenant_by_public_id`, from the webhooks and the Telegram polling) and
# internal ones (`tenant_by_id`, `tenant_by_slug`) throttle apart: whoever sprays unknown
# public ids from the internet cannot spend the slot the jobs rely on.
_miss_lock = threading.Lock()
_buckets = {"public": _Bucket(), "internal": _Bucket()}


def _after_fork_in_child() -> None:
    """A forked process (gunicorn with `--preload`, a worker) has none of the parent's
    threads, and may have inherited a lock held by one: start over with fresh primitives,
    keeping the loaded snapshot. Polling does not run in the child until it calls
    `start_polling` itself."""
    global _registry_lock, _refresh_cv, _refresh_state, _refresher, _refresher_pid, _rerun
    global _poll_interval, _stop_target, _miss_lock, _buckets
    global _beat_key, _beat_at, _beat_retry_at, _error_since, _polling_started_at
    _registry_lock = threading.Lock()
    _refresh_cv = threading.Condition()
    _refresh_state, _rerun = "idle", False
    _refresher, _refresher_pid = None, 0
    _poll_interval, _stop_target = None, None
    _miss_lock = threading.Lock()
    _buckets = {"public": _Bucket(), "internal": _Bucket()}
    # The child is another process: its own row, written from scratch.
    _beat_key, _beat_at, _beat_retry_at = None, float("-inf"), float("-inf")
    _error_since, _polling_started_at = None, None
    _last_logged.clear()


os.register_at_fork(after_in_child=_after_fork_in_child)


def reset_registry() -> None:
    """Clear the process cache, for tests and explicit operator reloads."""
    global _registry, _revision, _checked_at, _entries
    wait_for_refresh()
    with _registry_lock:
        _registry, _revision, _entries, _checked_at = None, None, None, 0.0
    with _miss_lock:
        for bucket in _buckets.values():
            bucket.last = float("-inf")


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


def warm_up_in_background(*, poll: bool = False) -> None:
    """`warm_up` on a daemon thread, for process boot that must not wait for it. With
    `poll`, the process also starts following the configuration on its own
    (`start_polling`): only real process boots (a web worker, a queue worker) ask for it;
    tests, management commands and the dev chat stay lazy."""

    def run() -> None:
        warm_up()
        if poll:
            start_polling()

    threading.Thread(target=run, name="registry-warm-up", daemon=True).start()


def start_polling(interval: float = POLL_SECONDS) -> None:
    """Make this process check the configuration revision every `interval` seconds on
    its own, even with nobody calling, and report it in `config_follower`. Idempotent;
    starts the refresher thread if this process has none. Never raises."""
    global _poll_interval, _polling_started_at, _atexit_registered
    with _refresh_cv:
        _poll_interval = interval
    if _polling_started_at is None:
        _polling_started_at = timezone.now()
    if not _atexit_registered:
        _atexit_registered = True
        atexit.register(_forget_process)  # a clean exit removes the row at once
    _request_refresh()  # starts the thread, or wakes it so it sees the interval


def stop_polling() -> None:
    """Stop the refresher thread and wait for it, then remove this process's row (tests
    and shutdown). A later lazy refresh request starts a new thread."""
    global _poll_interval, _stop_target
    with _refresh_cv:
        _poll_interval = None
        thread = _refresher
        if thread is not None and thread.is_alive() and _refresher_pid == os.getpid():
            _stop_target = thread
            _refresh_cv.notify_all()
        else:
            thread = None
    if thread is not None:
        thread.join(timeout=30)
        with _refresh_cv:
            if not thread.is_alive() and _stop_target is thread:
                _stop_target = None
            # Still alive after the wait: it stays the stop target and leaves by itself.
    _forget_process()


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


def _log_failure(key: str, message: str, error: BaseException | None = None) -> None:
    """Log a failure that repeats every poll: the first time with its traceback, then at
    most once a minute until `_log_recovered`."""
    now = time.monotonic()
    last = _last_logged.get(key)
    if last is not None and now - last < FAILURE_LOG_SECONDS:
        return
    _last_logged[key] = now
    if last is None:
        log.warning(message, exc_info=error or True)
    else:
        log.warning("%s (still failing: %s)", message, type(error).__name__ if error else "?")


def _log_recovered() -> None:
    if _last_logged:
        log.info("Configuration checks work again")
        _last_logged.clear()


def _reload_locked(now: float) -> Registry:
    """Check the revision and rebuild if it changed. Needs `_registry_lock`.

    The rebuild is incremental: only the tenants whose fingerprint changed are loaded
    again (the first load, and any inconsistency, rebuild everything). The new snapshot
    is published only once complete; if the rebuild fails the previous one stays (the
    first load propagates the error)."""
    global _registry, _revision, _checked_at, _last_reload_ok, _entries
    _last_reload_ok = False
    try:
        if _registry is not None and _read_revision() == _revision:
            _checked_at = now
            _last_reload_ok = True
            return _registry
        from packs.registry import PACKS

        previous = _entries if _registry is not None else None
        try:
            revision, entries, changed = _read_entries(previous, PACKS)
        except _Inconsistent:
            revision, entries, changed = _read_entries(None, PACKS)
        except DatabaseError:
            raise
        except Exception:
            if previous is None:
                raise
            log.exception("Incremental configuration reload failed; rebuilding everything")
            revision, entries, changed = _read_entries(None, PACKS)
        registry = _assemble(entries[tenant_id] for tenant_id in sorted(entries))
    except DatabaseError as error:
        if _registry is None:
            raise
        _checked_at = now
        _log_failure("reload", "Configuration reload failed; keeping the loaded registry", error)
        return _registry
    except Exception as error:
        if _registry is None:
            raise
        _checked_at = now
        _log_failure("reload", "Configuration rebuild failed; keeping the loaded registry", error)
        return _registry
    _registry, _revision, _entries, _checked_at = registry, revision, entries, now
    _last_reload_ok = True
    log.info(
        "Configuration reloaded: revision %s, %s tenants loaded, %s reused",
        revision,
        changed,
        len(entries) - changed,
    )
    return registry


class _Inconsistent(Exception):
    """The cached entries do not match the database's fingerprints: rebuild everything."""


def _read_entries(
    previous: Mapping[UUID, _Entry] | None, packs: Mapping[str, Pack]
) -> tuple[int, dict[UUID, _Entry], int]:
    """The revision, an entry for every tenant and how many were loaded now. With
    `previous`, a tenant whose fingerprint did not change keeps its entry."""
    known = (
        {tenant_id: entry.fingerprint for tenant_id, entry in previous.items()}
        if previous is not None
        else None
    )
    read = _read_config(known)
    if read.fingerprints is None:
        # A reader without fingerprints (a test's fake): every source is loaded.
        return (
            read.revision,
            {s.tenant_id or UUID(int=i): _load_entry(s, packs) for i, s in enumerate(read.sources)},
            len(read.sources),
        )
    loaded = {s.tenant_id: s for s in read.sources}
    entries: dict[UUID, _Entry] = {}
    for tenant_id, fingerprint in read.fingerprints.items():
        source = loaded.get(tenant_id)
        if source is not None:
            entries[tenant_id] = _load_entry(source, packs, fingerprint)
            continue
        entry = previous.get(tenant_id) if previous is not None else None
        if entry is None or entry.fingerprint != fingerprint:
            raise _Inconsistent
        entries[tenant_id] = entry
    return read.revision, entries, len(loaded)


def _read_config(known: Mapping[UUID, Fingerprint] | None) -> ConfigRead:
    """`read_config`, through a seam the tests can replace."""
    return read_config(known=known)


def _should_run(me: threading.Thread) -> bool:
    return _stop_target is me or (_refresh_state == "queued" and _refresher is me)


def _prepare_connection(polling: bool) -> None:
    """The refresher's connection before a check. Lazily it follows `CONN_MAX_AGE`; when
    polling it is kept open (a check every 2 s must not reconnect every time) and only
    dropped if an earlier error left it unusable."""
    connection = connections["default"]
    try:
        if polling:
            if connection.connection is not None and connection.errors_occurred:
                if connection.is_usable():
                    connection.errors_occurred = False  # healthy: do not test it every poll
                else:
                    connection.close()
        else:
            connection.close_if_unusable_or_obsolete()
            connection.close_if_health_check_failed()
    except Exception:
        # The kept connection is broken (or cannot even be checked): drop it and
        # still try the reload, which opens a fresh one, rather than skip this round.
        _drop_connection()


def _drop_connection() -> None:
    connections.close_all()


def _refresher_loop(cv: threading.Condition) -> None:
    """The refresher thread: one check/rebuild per request or, when polling, per
    interval, on its own connection. Every polling round ends with a heartbeat, whether
    it worked or not."""
    global _refresh_state, _refresher, _rerun
    me = threading.current_thread()
    while True:
        with cv:
            cv.wait_for(lambda: _should_run(me), timeout=_poll_interval)
            if _stop_target is me:
                # Leave under the lock, so that from now on a caller sees no refresher
                # (and starts another) instead of queueing for a thread that is gone.
                if _refresher is me:
                    _refresher, _refresh_state, _rerun = None, "idle", False
                cv.notify_all()
                break
            if _refresher is not me:
                break  # replaced (a fork's leftover): not its business any more
            _refresh_state = "running"
            _rerun = False
            polling = _poll_interval is not None
        _prepare_connection(polling)
        try:
            with _registry_lock:
                _reload_locked(time.monotonic())
                ok = _last_reload_ok
        except Exception as error:
            _log_failure("refresher", "Registry refresher failed", error)
            ok = False
        if ok:
            _log_recovered()
        else:
            _drop_connection()  # never keep a connection that just failed
        if polling:
            _note_round(ok)
            _beat(time.monotonic())
        with cv:
            _refresh_state = "queued" if _rerun else "idle"
            cv.notify_all()
    _drop_connection()


def _note_round(ok: bool) -> None:
    """Remember since when the checks have been failing (cleared by a good one)."""
    global _error_since
    if ok:
        _error_since = None
    elif _error_since is None:
        _error_since = timezone.now()


def _beat(now: float) -> None:
    """Tell the database which revision this process has loaded (`config_follower`, 0 if
    none yet) and since when its checks fail, if at all: when either changed or
    `HEARTBEAT_SECONDS` have passed since the last write, and after every polling round,
    so a live process never goes silent. Refresher thread only, on its own connection and
    in autocommit: never on the hot path, never inside a request or job transaction. A
    failure is logged and ignored (retried after `HEARTBEAT_SECONDS`); it never breaks
    the refresher."""
    global _beat_key, _beat_at, _beat_retry_at
    if now < _beat_retry_at:
        return
    revision = _revision or 0
    error_since = _error_since
    key = (revision, error_since is not None)
    if key == _beat_key and now - _beat_at < HEARTBEAT_SECONDS:
        return
    try:
        _write_beat(revision, error_since)
    except Exception as error:
        _beat_retry_at = now + HEARTBEAT_SECONDS
        _log_failure("heartbeat", "Configuration heartbeat failed; will retry", error)
        return
    _beat_key, _beat_at = key, now


def _write_beat(revision: int, last_error_at: datetime | None) -> None:
    """Upsert this process's `config_follower` row (one statement, default connection)."""
    global _polling_started_at
    from django.conf import settings

    from autobot.tenancy.models import ConfigFollower

    if _polling_started_at is None:
        _polling_started_at = timezone.now()
    ConfigFollower.objects.bulk_create(
        [
            ConfigFollower(
                service=settings.SERVICE_NAME,
                host=socket.gethostname(),
                pid=os.getpid(),
                revision=revision,
                started_at=_polling_started_at,
                seen_at=timezone.now(),
                last_error_at=last_error_at,
            )
        ],
        update_conflicts=True,
        unique_fields=["host", "pid"],
        update_fields=["service", "revision", "started_at", "seen_at", "last_error_at"],
    )


FORGET_TIMEOUT_MS = 2000
FORGET_CONNECT_TIMEOUT_S = 2


def _forget_process() -> None:
    """Remove this process's row when it stops on purpose (`stop_polling`, and `atexit`
    on a clean exit); a process that just dies leaves a row that readers ignore once it is
    35 s old. Best effort and bounded: its own short-lived connection, with a connect and
    a statement timeout, so shutdown never waits on a sick database."""
    global _beat_key
    if _beat_key is None:
        return
    _beat_key = None
    connection = None
    try:
        connection = connections.create_connection("default")
        options = dict(connection.settings_dict.get("OPTIONS") or {})
        options["connect_timeout"] = FORGET_CONNECT_TIMEOUT_S
        connection.settings_dict = {**connection.settings_dict, "OPTIONS": options}
        with connection.cursor() as cursor:
            cursor.execute(f"SET statement_timeout = {FORGET_TIMEOUT_MS}")
            cursor.execute(
                "DELETE FROM config_follower WHERE host = %s AND pid = %s",
                [socket.gethostname(), os.getpid()],
            )
    except Exception:
        log.warning("Configuration heartbeat cleanup failed", exc_info=True)
    finally:
        if connection is not None:
            try:
                connection.close()
            except Exception:
                log.debug("Closing the cleanup connection failed", exc_info=True)


def _request_refresh() -> None:
    """Ask the refresher for one check: queue it, or note that one more is wanted if it
    is running right now (that one may have read the revision before the caller's write).
    Starts a thread if there is none, or the one there is is being stopped."""
    global _refresher, _refresher_pid, _refresh_state, _rerun
    with _refresh_cv:
        if _refresh_state == "running":
            _rerun = True
            return
        if _refresh_state != "idle":
            return
        current = _refresher
        if (
            current is None
            or _refresher_pid != os.getpid()
            or not current.is_alive()
            or _stop_target is current
        ):
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
    """Stale-while-revalidate for the hot path. Within 2 s of the last check the loaded
    snapshot is returned. After that, the first caller wakes the process's single
    refresher thread, which checks the revision and rebuilds if it changed; everyone keeps
    using the previous snapshot until the new one is swapped in, so no request or job
    waits for a rebuild. In a booted process the refresher also polls on its own
    (`start_polling`), so that snapshot is at most about one interval old even after hours
    without callers.

    Synchronous (blocking) paths: the very first load, and `force`, which skips the
    window and re-checks the revision now, taking `_registry_lock` (it waits for a rebuild
    in flight). Only code that is not on a public request path uses `force`: the panel
    (authenticated, behind the tunnel, and the rebuild is incremental) and tests. A
    lookup miss never does, see `_lookup`."""
    global _checked_at
    now = time.monotonic()
    current = _registry
    if not force and current is not None and now - _checked_at < POLL_SECONDS:
        return current
    if not force and current is not None:
        _checked_at = now  # one check per window, whatever the rebuild takes
        _request_refresh()
        return current
    with _registry_lock:
        now = time.monotonic()
        if not force and _registry is not None and now - _checked_at < POLL_SECONDS:
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


def _in_transaction() -> bool:
    """Whether this thread has a transaction open on any connection: a lookup inside one
    never waits (it would hold the transaction's locks meanwhile)."""
    return any(c.in_atomic_block for c in connections.all(initialized_only=True))


def _newest() -> Registry | None:
    """The newest snapshot this process has published, whatever a scope pinned."""
    return _registry


def _lookup(
    find: Callable[[Registry], LoadedTenant | None], *, public: bool
) -> LoadedTenant | None:
    """`find` in the current snapshot; on a miss, check whether the configuration moved
    on, wait a bounded time for this process to follow, and look again in the newest
    snapshot.

    Never rebuilds on the caller's thread and never takes `_registry_lock`: it reads the
    revision (one query), and if it differs asks the refresher thread, waiting at most
    `MISS_WAIT_SECONDS` for it. At most one such check per `MISS_RETRY_SECONDS` runs in
    each bucket (public, from the internet; internal), and a miss that arrives while the
    bucket's check is in flight waits for that check instead of answering at once. A miss
    inside a transaction never waits. Under a spray of unknown public ids the bucket may
    answer None for a tenant written a moment ago: the provider retries, and the 2 s
    polling closes the gap.

    A `registry_scope` is not re-pinned: the tenant found is returned, the snapshot the
    unit of work pinned stays as it was."""
    tenant = find(get_registry())
    if tenant is not None:
        return tenant
    newest = _newest()
    if _in_transaction():
        _request_refresh()  # the next caller finds it; this one must not wait
        return find(newest) if newest is not None else None
    bucket = _buckets["public" if public else "internal"]
    with _miss_lock:
        now = time.monotonic()
        inflight = bucket.inflight
        leader = inflight is None and now - bucket.last >= MISS_RETRY_SECONDS
        if leader:
            bucket.last = now
            bucket.inflight = inflight = threading.Event()
    if leader:
        assert inflight is not None
        try:
            _wait_for_newer_config()
        finally:
            with _miss_lock:
                bucket.inflight = None
            inflight.set()
    elif inflight is not None:
        inflight.wait(MISS_WAIT_SECONDS)
    newest = _newest()
    tenant = find(newest) if newest is not None else None
    if tenant is not None:
        log.info("Tenant %s was missing from the snapshot; found after a check", tenant.id)
    return tenant


def _wait_for_newer_config() -> None:
    """If the database's revision is not the one loaded, ask the refresher and wait (at
    most `MISS_WAIT_SECONDS`) for it to publish. Never raises, never rebuilds here."""
    try:
        wanted = _read_revision()
    except Exception as error:
        _log_failure("miss-check", "Revision check after a lookup miss failed", error)
        return
    loaded = _revision
    if wanted == loaded:
        return
    _request_refresh()
    with _refresh_cv:
        _refresh_cv.wait_for(lambda: _revision != loaded, MISS_WAIT_SECONDS)


def tenant_by_id(tenant_id: UUID) -> LoadedTenant | None:
    return _lookup(lambda r: r.by_id.get(tenant_id), public=False)


def tenant_by_slug(slug: str) -> LoadedTenant | None:
    return _lookup(lambda r: r.by_slug.get(slug), public=False)


def tenant_by_public_id(kind: str, public_id: str) -> LoadedTenant | None:
    return _lookup(lambda r: r.by_public_id.get((kind, public_id)), public=True)
