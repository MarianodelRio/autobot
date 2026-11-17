"""The single, serialized and audited path for tenant configuration writes."""

import copy
import hashlib
import json
import secrets as random_secrets
import string
from collections.abc import Mapping
from dataclasses import replace
from typing import Any, Literal
from uuid import uuid7

from django.db import transaction
from django.utils import timezone
from pydantic import ValidationError
from pydantic_core import ErrorDetails

from autobot.ops.audit import record
from autobot.tenancy.crypto import encrypt
from autobot.tenancy.models import (
    ConfigRevision,
    Tenant,
    TenantDatasetVersion,
    TenantDocumentVersion,
    TenantSecret,
)
from autobot.tenancy.registry import (
    TenantSource,
    load_registry,
    sources_from_database,
)
from autobot.tenancy.schema import SECRETS_SCHEMA, TenantDocument

IDENTITY = (
    ("id",),
    ("slug",),
    ("pack",),
    ("status",),
    ("channel", "type"),
    ("channel", "public_id"),
)


class StoreError(Exception):
    def __init__(self, code: str, message: str, details: list[str] | None = None) -> None:
        self.code, self.message, self.details = code, message, details or []
        super().__init__(message)


# Pydantic's own error type → a short, generic Spanish message (C7). `value_error`
# (a pack's or the schema's own `raise ValueError(...)`, already written in Spanish)
# keeps its message instead, since it is the only type with business meaning.
_TYPE_MESSAGES: dict[str, str] = {
    "missing": "falta este campo",
    "string_type": "debe ser un texto",
    "string_too_short": "es demasiado corto",
    "string_too_long": "es demasiado largo",
    "string_pattern_mismatch": "no tiene el formato esperado",
    "int_type": "debe ser un número entero",
    "int_parsing": "debe ser un número entero",
    "float_type": "debe ser un número",
    "bool_type": "debe ser verdadero o falso",
    "list_type": "debe ser una lista",
    "too_short": "tiene muy pocos elementos",
    "too_long": "tiene demasiados elementos",
    "dict_type": "debe ser un objeto",
    "extra_forbidden": "campo no reconocido",
    "literal_error": "valor no permitido",
    "greater_than": "debe ser mayor que el mínimo",
    "greater_than_equal": "debe ser mayor o igual que el mínimo",
    "less_than": "debe ser menor que el máximo",
    "less_than_equal": "debe ser menor o igual que el máximo",
    "uuid_parsing": "no es un identificador válido",
    "date_parsing": "no es una fecha válida",
    "datetime_parsing": "no es una fecha y hora válidas",
    "url_parsing": "no es una URL válida",
    "union_tag_invalid": "tipo no reconocido",
    "union_tag_not_found": "falta el campo que indica el tipo",
}


def _message(item: ErrorDetails) -> str:
    if item["type"] == "value_error":
        # "Value error, <custom message>" → "<custom message>" (the message a pack's
        # or the schema's own validator raised, already in Spanish).
        return str(item["msg"]).removeprefix("Value error, ")
    return _TYPE_MESSAGES.get(item["type"], "valor no válido")


def _validation(error: ValidationError, prefix: str = "") -> StoreError:
    details = [
        f"{prefix}{'.'.join(str(part) for part in item['loc']) or '(root)'}: {_message(item)}"
        for item in error.errors(include_input=False, include_context=False)
    ]
    return StoreError("validation_error", "La configuración no es válida", details)


def _document(raw: dict[str, Any]) -> dict[str, Any]:
    try:
        return TenantDocument.model_validate(raw).model_dump(mode="json")
    except ValidationError as error:
        raise _validation(error) from None


def _value(document: dict[str, Any], path: tuple[str, ...]) -> Any:
    value: Any = document
    for key in path:
        value = value.get(key) if isinstance(value, dict) else None
    return value


def current_sources(alias: str = "owner") -> list[TenantSource]:
    return sources_from_database(alias)[1]


def _current(slug: str, sources: list[TenantSource]) -> TenantSource:
    for source in sources:
        if isinstance(source.document, dict) and source.document.get("slug") == slug:
            return source
    raise StoreError("not_found", "No se encuentra el negocio")


def _lock() -> ConfigRevision:
    return ConfigRevision.objects.using("owner").select_for_update().get(pk=1)


def _validate(source: TenantSource, sources: list[TenantSource]) -> None:
    from packs.registry import PACKS

    document = _document(source.document)
    source = replace(source, document=document)
    if any(not isinstance(name, str) or not 1 <= len(name) <= 64 for name in source.datasets):
        raise StoreError(
            "validation_error", "Nombre de dataset no válido", ["datasets: nombre no válido"]
        )
    pack = PACKS.get(document["pack"])
    if pack is None:
        raise StoreError(
            "validation_error", "La configuración no es válida", ["pack: pack no disponible"]
        )
    try:
        pack.config_schema.model_validate(document["config"])
    except ValidationError as error:
        raise _validation(error, "config.") from None
    candidates = [
        s
        for s in sources
        if not isinstance(s.document, dict) or s.document.get("id") != document["id"]
    ] + [source]
    registry = load_registry(candidates, PACKS)
    tenant = registry.by_slug.get(document["slug"])
    if document["slug"] in registry.errors or tenant is None:
        raise StoreError(
            "validation_error", "El documento no es válido", ["document: documento no válido"]
        )
    if tenant.is_degraded or tenant.ambiguous:
        duplicate = [
            name
            for name in ("id", "public_id", "phone_number_id")
            if f"{name} repeated" in tenant.degraded
        ]
        # C5: surface the real reason (e.g. a bus town missing from its dataset)
        # instead of a generic, unhelpful message.
        details = (
            [f"{name}: valor repetido" for name in duplicate]
            or [f"datasets: {reason}" for reason in tenant.degraded]
            or ["datasets: datos no válidos"]
        )
        raise StoreError("validation_error", "La configuración no es válida", details)


def _bump(revision: ConfigRevision) -> None:
    revision.revision += 1
    revision.save(using="owner", update_fields=["revision", "updated_at"])


def _write(
    source: TenantSource,
    revision: ConfigRevision,
    *,
    actor: str,
    comment: str,
    action: str,
    summary: str,
) -> int:
    doc = source.document
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
    latest = (
        TenantDocumentVersion.objects.using("owner")
        .filter(tenant=tenant)
        .order_by("-version")
        .first()
    )
    version = latest.version + 1 if latest else 1
    TenantDocumentVersion.objects.using("owner").create(
        tenant=tenant,
        version=version,
        document=doc,
        author=actor,
        comment=comment,
    )
    _bump(revision)
    record(
        actor=actor,
        action=action,
        tenant_id=tenant.id,
        target_type="tenant",
        target_id=str(tenant.id),
        summary=summary,
        details={"version": version, "comment": comment},
    )
    return version


def new_document(
    *,
    pack: str,
    slug: str,
    name: str,
    timezone: str,
    channel_type: Literal["whatsapp", "telegram"] | None,
    demo_description: str | None,
    config: dict[str, Any],
) -> dict[str, Any]:
    from packs.registry import PACKS

    pack_obj = PACKS.get(pack)
    doc: dict[str, Any] = {
        "id": str(uuid7()),
        "slug": slug,
        "name": name,
        "timezone": timezone,
        "pack": pack,
        "config": copy.deepcopy(config),
        "status": "paused" if demo_description is not None else "onboarding",
        # C8: every notice the pack can emit, on by default, same as the demo;
        # the operator unchecks what it does not want. Without this, a dueño who
        # just linked their chat receives nothing until someone notices and edits
        # the YAML by hand.
        "owner": {
            "notify": [notice.kind for notice in pack_obj.owner_notices] if pack_obj else [],
            "summary_monthly": True,
        },
    }
    if demo_description is not None:
        if channel_type is not None:
            raise StoreError("bad_request", "Un demo no puede tener canal propio")
        doc["demo"] = {"description": demo_description}
    elif channel_type in ("whatsapp", "telegram"):
        alphabet = string.ascii_lowercase + string.digits
        channel: dict[str, Any] = {
            "type": channel_type,
            "public_id": "".join(random_secrets.choice(alphabet) for _ in range(16)),
        }
        channel.update(
            {"app_id": None, "waba_id": None, "phone_number_id": None}
            if channel_type == "whatsapp"
            else {"bot_username": None}
        )
        doc["channel"] = channel
        doc["testers"] = {"main": []}
    else:
        raise StoreError("bad_request", "El negocio necesita un canal o una descripción de demo")
    return doc


def _secrets(channel_type: str, raw: Mapping[str, str]) -> dict[str, str]:
    try:
        validated = SECRETS_SCHEMA[channel_type].model_validate(raw)
    except ValidationError as error:
        raise _validation(error, "secrets.") from None
    return {key: value.get_secret_value() for key, value in validated.model_dump().items()}


def _write_secret(source: TenantSource, raw: Mapping[str, str], actor: str) -> None:
    doc = source.document
    TenantSecret.objects.using("owner").update_or_create(
        tenant_id=doc["id"],
        defaults={
            "channel_type": doc["channel"]["type"],
            "ciphertext": encrypt(raw),
            "updated_by": actor,
        },
    )
    record(
        actor=actor,
        action="tenant.secrets",
        tenant_id=TenantDocument.model_validate(doc).id,
        target_type="tenant",
        target_id=doc["id"],
        summary="Secretos de canal sustituidos",
        details={"fields": sorted(raw)},
    )


@transaction.atomic(using="owner")
def create_tenant(
    *,
    document: dict[str, Any],
    datasets: Mapping[str, Mapping[str, str]] | None = None,
    dataset_origins: Mapping[str, tuple[str, int, str]] | None = None,
    secrets: Mapping[str, str] | None = None,
    actor: str,
    comment: str,
    keep_status: bool = False,
) -> int:
    from packs.registry import PACKS

    revision = _lock()
    raw = copy.deepcopy(document)
    if not keep_status:
        raw["status"] = "paused" if raw.get("demo") is not None else "onboarding"
    doc = _document(raw)
    if TenantDocumentVersion.objects.using("owner").filter(tenant_id=doc["id"]).exists():
        raise StoreError("conflict", "El negocio ya tiene configuración")
    if Tenant.objects.using("owner").filter(slug=doc["slug"]).exclude(pk=doc["id"]).exists():
        raise StoreError("conflict", "El slug ya existe")
    pack = PACKS.get(doc["pack"])
    # C4: a pack that needs datasets (e.g. bus's timetable) must have one chosen
    # explicitly (ADR-013's library). Silently copying the demo template's own —
    # fictional — dataset left a new client with it unnoticed; `seed_demos` and
    # `tenant_config import` always pass their own datasets explicitly, so this
    # never fires for them.
    if pack is not None and pack.load_data is not None and not datasets:
        raise StoreError(
            "bad_request",
            "Este pack necesita un conjunto de datos elegido de la biblioteca",
            ["datasets: hay que elegir uno antes de crear el negocio"],
        )
    raw_secrets = None
    if secrets is not None:
        if doc["channel"] is None:
            raise StoreError("bad_request", "Un demo no admite secretos de canal")
        raw_secrets = _secrets(doc["channel"]["type"], secrets)
    source = TenantSource(doc["slug"], doc, datasets=datasets or {}, secrets=raw_secrets)
    _validate(source, current_sources())
    version = _write(
        source,
        revision,
        actor=actor,
        comment=comment,
        action="tenant.create",
        summary="Negocio creado",
    )
    if raw_secrets is not None:
        _write_secret(source, raw_secrets, actor)
    for name, files in (datasets or {}).items():
        origin = (dataset_origins or {}).get(name)
        _write_dataset(source, name, files, actor=actor, comment=comment, library_origin=origin)
    return version


@transaction.atomic(using="owner")
def publish(
    slug: str, *, document: dict[str, Any], base_version: int, actor: str, comment: str
) -> int:
    revision = _lock()
    sources = current_sources()
    current = _current(slug, sources)
    if current.version != base_version:
        raise StoreError("conflict", "Hay una versión más reciente; recarga la configuración")
    doc = _document(document)
    if any(_value(doc, path) != _value(current.document, path) for path in IDENTITY):
        raise StoreError(
            "forbidden_change",
            "La publicación no permite cambiar la identidad, el estado o el tipo de canal",
        )
    candidate = replace(current, document=doc)
    _validate(candidate, sources)
    return _write(
        candidate,
        revision,
        actor=actor,
        comment=comment,
        action="tenant.publish",
        summary="Configuración publicada",
    )


@transaction.atomic(using="owner")
def rollback(slug: str, *, version: int, actor: str, comment: str) -> int:
    revision = _lock()
    sources = current_sources()
    current = _current(slug, sources)
    previous = (
        TenantDocumentVersion.objects.using("owner")
        .filter(tenant_id=current.document["id"], version=version)
        .first()
    )
    if previous is None:
        raise StoreError("not_found", "No se encuentra la versión")
    doc = copy.deepcopy(previous.document)
    for key in ("id", "slug", "pack", "status"):
        doc[key] = current.document[key]
    old_channel, channel = doc.get("channel"), current.document.get("channel")
    if channel is None:
        doc["channel"] = None
    else:
        if not isinstance(old_channel, dict) or old_channel.get("type") != channel["type"]:
            doc["channel"] = copy.deepcopy(channel)
        else:
            doc["channel"]["type"] = channel["type"]
            doc["channel"]["public_id"] = channel["public_id"]
    candidate = replace(current, document=_document(doc))
    _validate(candidate, sources)
    return _write(
        candidate,
        revision,
        actor=actor,
        comment=comment,
        action="tenant.rollback",
        summary="Configuración recuperada",
    )


def change_status(
    slug: str,
    *,
    action: Literal["activate", "pause", "resume", "offboard"],
    actor: str,
    confirm_slug: str | None = None,
) -> int:
    from autobot.tenancy.activation import checklist

    transitions = {
        "activate": ({"onboarding"}, "active"),
        "pause": ({"active"}, "paused"),
        "resume": ({"paused"}, "active"),
        "offboard": ({"active", "paused", "onboarding"}, "offboarded"),
    }
    if action not in transitions:
        raise StoreError("bad_request", "Acción de estado no válida")
    if action in ("activate", "offboard") and confirm_slug != slug:
        raise StoreError("bad_request", "Escribe el slug para confirmar")
    if action == "activate":
        before = _current(slug, current_sources())
        if before.document.get("status") != "onboarding" or before.document.get("demo") is not None:
            raise StoreError("invalid_status", "El estado no permite esta acción")
        if checklist(slug).blocking:
            raise StoreError("bad_request", "La activación tiene comprobaciones pendientes")
    with transaction.atomic(using="owner"):
        revision = _lock()
        sources = current_sources()
        current = _current(slug, sources)
        allowed, status = transitions[action]
        if current.document["status"] not in allowed:
            raise StoreError("invalid_status", "El estado no permite esta acción")
        doc = _document({**current.document, "status": status})
        candidate = replace(current, document=doc)
        if action != "pause":
            # Pausing must always be possible, even for a tenant degraded for a reason
            # unrelated to this change (X10): it changes nothing else, so there is
            # nothing new to validate, and it is precisely the way to take a broken
            # tenant out of service.
            _validate(candidate, sources)
        return _write(
            candidate,
            revision,
            actor=actor,
            comment=action,
            action="tenant.status",
            summary=f"Estado cambiado a {status}",
        )


@transaction.atomic(using="owner")
def set_secrets(slug: str, *, secrets: Mapping[str, str], actor: str) -> None:
    revision = _lock()
    sources = current_sources()
    current = _current(slug, sources)
    channel = _document(current.document).get("channel")
    if channel is None or current.document.get("demo") is not None:
        raise StoreError("bad_request", "Un demo no admite secretos de canal")
    # Partial substitution: blank (or whitespace-only, C11) or absent fields keep
    # the currently readable secrets. If a field is missing from both, validation
    # below rejects it.
    provided = {name: value.strip() for name, value in secrets.items() if value.strip()}
    existing = current.secrets or {}
    merged = {**existing, **provided}
    raw = _secrets(channel["type"], merged)
    candidate = replace(current, secrets=raw, secrets_error=None)
    _validate(candidate, sources)
    _write_secret(candidate, raw, actor)
    _bump(revision)


def _dataset_digest(files: Mapping[str, str]) -> str:
    if any(not isinstance(path, str) or not isinstance(text, str) for path, text in files.items()):
        raise StoreError(
            "validation_error", "Dataset no válido", ["datasets: solo se admite texto UTF-8"]
        )
    return hashlib.sha256(json.dumps(dict(files), sort_keys=True).encode()).hexdigest()


def _write_dataset(
    source: TenantSource,
    name: str,
    files: Mapping[str, str],
    *,
    actor: str,
    comment: str,
    library_origin: tuple[str, int, str] | None = None,
) -> int:
    tenant_id = source.document["id"]
    prior = (
        TenantDatasetVersion.objects.using("owner")
        .filter(tenant_id=tenant_id, name=name)
        .order_by("-version")
        .first()
    )
    version = prior.version + 1 if prior else 1
    source_name, source_version, source_sha = library_origin or (None, None, None)
    TenantDatasetVersion.objects.using("owner").create(
        tenant_id=tenant_id,
        name=name,
        files=dict(files),
        version=version,
        sha256=_dataset_digest(files),
        author=actor,
        comment=comment,
        source_name=source_name,
        source_version=source_version,
        source_sha=source_sha,
    )
    record(
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
    library_origin: tuple[str, int, str] | None = None,
) -> int | None:
    revision = _lock()
    sources = current_sources()
    current = _current(slug, sources)
    digest = _dataset_digest(files)
    previous = (
        TenantDatasetVersion.objects.using("owner")
        .filter(tenant_id=current.document["id"], name=name)
        .order_by("-version")
        .first()
    )
    if previous is not None and previous.sha256 == digest:
        return None
    candidate = replace(current, datasets={**current.datasets, name: files})
    _validate(candidate, sources)
    version = _write_dataset(
        candidate, name, files, actor=actor, comment=comment, library_origin=library_origin
    )
    _bump(revision)
    return version


@transaction.atomic(using="owner")
def import_source(source: TenantSource, *, actor: str, comment: str) -> int:
    """Validate a directory's document and datasets together before publishing either."""
    revision = _lock()
    doc = _document(source.document)
    sources = current_sources()
    existing = [
        s for s in sources if isinstance(s.document, dict) and s.document.get("slug") == doc["slug"]
    ]
    if not existing:
        return create_tenant(
            document=doc,
            datasets=source.datasets or None,
            secrets=source.secrets,
            actor=actor,
            comment=comment,
            keep_status=True,
        )
    current = existing[0]
    if any(_value(doc, path) != _value(current.document, path) for path in IDENTITY):
        raise StoreError(
            "forbidden_change",
            "La importación no permite cambiar la identidad, el estado o el tipo de canal",
        )
    raw_secrets = None
    if source.secrets is not None:
        if doc.get("channel") is None:
            raise StoreError("bad_request", "Un demo no admite secretos de canal")
        raw_secrets = _secrets(doc["channel"]["type"], source.secrets)
    candidate = replace(
        current,
        document=doc,
        datasets={**current.datasets, **source.datasets},
        secrets=current.secrets if raw_secrets is None else raw_secrets,
        secrets_error=current.secrets_error if raw_secrets is None else None,
    )
    _validate(candidate, sources)
    version = _write(
        candidate,
        revision,
        actor=actor,
        comment=comment,
        action="tenant.publish",
        summary="Configuración importada",
    )
    for name, files in source.datasets.items():
        prior = (
            TenantDatasetVersion.objects.using("owner")
            .filter(tenant_id=doc["id"], name=name)
            .order_by("-version")
            .first()
        )
        if prior is None or prior.sha256 != _dataset_digest(files):
            _write_dataset(candidate, name, files, actor=actor, comment=comment)
    if raw_secrets is not None:
        _write_secret(candidate, raw_secrets, actor)
    return version
