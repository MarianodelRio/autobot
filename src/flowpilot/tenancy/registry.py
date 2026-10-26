"""Tenant registry: tenants/*/tenant.yaml + secrets → memory.

`load_registry` reads every tenant, validates the common part, the pack's config and the
channel secrets, loads the datasets and builds the indexes. A broken tenant never affects
the others:

- unreadable file, invalid YAML or an invalid common part: the tenant cannot be
  identified, so it is left out and reported in `Registry.errors`;
- unknown pack, invalid config, failing `load_data` or a repeated id/public_id/
  phone_number_id: the tenant is `degraded` (its contacts get the generic text);
  a repeated key also makes it `ambiguous`: it is never routed nor synced;
- missing secrets or channel ids: only its `main` channel is disabled (the test bot keeps
  working).

Messages never contain secret values.
"""

import logging
from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass, field, replace
from functools import cache
from pathlib import Path
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

import yaml
from django.conf import settings
from pydantic import BaseModel, ValidationError

from core.pack import Pack, TenantInfo
from flowpilot.tenancy.schema import SECRETS_SCHEMA, ChannelSecrets, TenantFile

log = logging.getLogger(__name__)

# Problems reading a file: none of them may stop the other tenants from loading.
READ_ERRORS = (OSError, UnicodeDecodeError, yaml.YAMLError)


@dataclass(frozen=True)
class LoadedTenant:
    file: TenantFile
    path: Path
    pack: Pack | None = None
    config: BaseModel | None = None
    data: object | None = None
    secrets: ChannelSecrets | None = None
    degraded: list[str] = field(default_factory=list)  # reasons; empty = healthy
    main_disabled: list[str] = field(default_factory=list)  # why the main channel is off
    ambiguous: bool = False  # shares an id/public_id/phone_number_id with another tenant

    @property
    def id(self) -> UUID:
        return self.file.id

    @property
    def slug(self) -> str:
        return self.file.slug

    @property
    def is_degraded(self) -> bool:
        return bool(self.degraded)

    @property
    def main_enabled(self) -> bool:
        return not self.main_disabled

    @property
    def info(self) -> TenantInfo:
        f = self.file
        return TenantInfo(id=f.id, slug=f.slug, name=f.name, timezone=ZoneInfo(f.timezone))


@dataclass
class Registry:
    tenants: list[LoadedTenant] = field(default_factory=list)
    errors: dict[str, list[str]] = field(default_factory=dict)  # directory → problems
    secrets_error: str | None = None
    by_id: dict[UUID, LoadedTenant] = field(default_factory=dict)
    by_slug: dict[str, LoadedTenant] = field(default_factory=dict)
    by_public_id: dict[tuple[str, str], LoadedTenant] = field(default_factory=dict)
    by_phone_number_id: dict[str, LoadedTenant] = field(default_factory=dict)
    by_tester: dict[int, list[LoadedTenant]] = field(default_factory=dict)

    def tenant(self, tenant_id: UUID) -> LoadedTenant:
        return self.by_id[tenant_id]

    def serving(self, pack: str) -> list[LoadedTenant]:
        """Tenants of `pack` that run its periodic work: not degraded nor offboarded."""
        return [
            t
            for t in self.tenants
            if t.file.pack == pack and not t.is_degraded and t.file.status != "offboarded"
        ]

    def visible_to(self, telegram_user_id: int, operators: Collection[int]) -> list[LoadedTenant]:
        """Tenants a Telegram user may pick in the test bot: all for an operator,
        otherwise those that list them in testers.telegram. Availability (degraded,
        offboarded, test calendar) is the selector's business."""
        if telegram_user_id in operators:
            return [t for t in self.tenants if not t.ambiguous]
        return list(self.by_tester.get(telegram_user_id, []))

    @property
    def problems(self) -> dict[str, list[str]]:
        """Everything that should fail CI: unreadable and degraded tenants, and a broken
        secrets file."""
        found = {name: list(problems) for name, problems in self.errors.items()}
        for t in self.tenants:
            if t.degraded:
                found.setdefault(t.slug, []).extend(t.degraded)
        if self.secrets_error:
            found["secrets.yaml"] = [self.secrets_error]
        return found


def load_registry(
    tenants_dir: Path, secrets_file: Path | None, packs: Mapping[str, Pack]
) -> Registry:
    registry = Registry()
    secrets = _read_secrets(secrets_file, registry)
    if not tenants_dir.is_dir():
        log.warning("No tenants directory at %s", tenants_dir)
        return registry
    for path in sorted(p for p in tenants_dir.iterdir() if p.is_dir()):
        if not (path / "tenant.yaml").is_file():
            registry.errors[path.name] = ["no tenant.yaml"]
            continue
        tenant = _load_tenant(path, packs, secrets, registry)
        if tenant is not None:
            registry.tenants.append(tenant)
    _mark_duplicates(registry)
    _index(registry)

    unknown = sorted(set(secrets) - set(registry.by_slug))
    if unknown:
        log.warning("secrets.yaml has entries for unknown tenants: %s", ", ".join(unknown))
    if registry.secrets_error:
        log.error("secrets.yaml cannot be used: %s", registry.secrets_error)
    for name, problems in registry.problems.items():
        if name != "secrets.yaml":
            log.error("Tenant %s cannot serve: %s", name, "; ".join(problems))
    for t in registry.tenants:
        if t.main_disabled and not t.is_degraded:
            log.warning("Tenant %s main channel disabled: %s", t.slug, "; ".join(t.main_disabled))
    return registry


def _read_secrets(secrets_file: Path | None, registry: Registry) -> dict[str, Any]:
    if secrets_file is None or not secrets_file.is_file():
        log.warning("No secrets file: every main channel is disabled")
        return {}
    try:
        data = yaml.safe_load(secrets_file.read_text()) or {}
    except READ_ERRORS as e:
        registry.secrets_error = f"cannot be read ({type(e).__name__})"
        return {}
    if not isinstance(data, dict) or not all(isinstance(k, str) for k in data):
        registry.secrets_error = "must map each tenant slug to its secrets"
        return {}
    return data


def _load_tenant(
    path: Path, packs: Mapping[str, Pack], secrets: Mapping[str, Any], registry: Registry
) -> LoadedTenant | None:
    try:
        raw = yaml.safe_load((path / "tenant.yaml").read_text())
    except READ_ERRORS as e:
        registry.errors[path.name] = [f"tenant.yaml cannot be read ({type(e).__name__})"]
        return None
    try:
        file = TenantFile.model_validate(raw)
    except ValidationError as e:
        registry.errors[path.name] = _describe(e)
        return None
    if file.slug != path.name:
        registry.errors[path.name] = [f"slug {file.slug!r} does not match its directory"]
        return None

    tenant = LoadedTenant(file=file, path=path)
    tenant = _with_pack(tenant, packs)
    return _with_secrets(tenant, secrets.get(file.slug))


def _with_pack(tenant: LoadedTenant, packs: Mapping[str, Pack]) -> LoadedTenant:
    pack = packs.get(tenant.file.pack)
    if pack is None:
        return _degrade(tenant, f"unknown pack {tenant.file.pack!r}")
    try:
        config = pack.config_schema.model_validate(tenant.file.config)
    except ValidationError as e:
        return _degrade(tenant, *(f"config: {m}" for m in _describe(e)))
    data = None
    if pack.load_data is not None:
        try:
            data = pack.load_data(tenant.info, config, tenant.path)
        except Exception as e:  # any failure loading a dataset degrades only this tenant
            return _degrade(tenant, f"load_data failed: {type(e).__name__}: {e}")
    return replace(tenant, pack=pack, config=config, data=data)


def _with_secrets(tenant: LoadedTenant, raw: Any) -> LoadedTenant:
    channel = tenant.file.channel
    disabled = [] if channel.complete else [f"{channel.type} channel ids are missing"]
    schema = SECRETS_SCHEMA[channel.type]
    secrets = None
    if raw is None:
        disabled.append("no secrets in secrets.yaml")
    else:
        try:
            secrets = schema.model_validate(raw)
        except ValidationError as e:
            disabled.extend(f"secrets: {m}" for m in _describe(e))
    return replace(tenant, secrets=secrets, main_disabled=disabled)


def _mark_duplicates(registry: Registry) -> None:
    def keys(t: LoadedTenant) -> Iterable[tuple[str, str]]:
        yield "id", str(t.id)
        yield "public_id", t.file.channel.public_id
        if t.file.channel.type == "whatsapp" and t.file.channel.phone_number_id:
            yield "phone_number_id", t.file.channel.phone_number_id

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
        registry.by_public_id[(t.file.channel.type, t.file.channel.public_id)] = t
        if t.file.channel.type == "whatsapp" and t.file.channel.phone_number_id:
            registry.by_phone_number_id[t.file.channel.phone_number_id] = t
        for user_id in t.file.testers.telegram:
            registry.by_tester.setdefault(user_id, []).append(t)


def _degrade(tenant: LoadedTenant, *reasons: str) -> LoadedTenant:
    return replace(tenant, degraded=[*tenant.degraded, *reasons])


def _describe(error: ValidationError) -> list[str]:
    """Field and message of each problem, never the input (it may hold a secret)."""
    return [f"{'.'.join(str(p) for p in e['loc']) or '(root)'}: {e['msg']}" for e in error.errors()]


@cache
def get_registry() -> Registry:
    """The process-wide registry, loaded on first use from settings.TENANTS_DIR and
    settings.SECRETS_FILE with the packs of packs.registry."""
    from packs.registry import PACKS

    return load_registry(settings.TENANTS_DIR, settings.SECRETS_FILE, PACKS)
