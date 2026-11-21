"""Validation of a candidate tenant against the rest of the platform, and the
serialization lock every write takes first."""

from collections.abc import Mapping
from dataclasses import replace
from typing import Any

from pydantic import ValidationError

from autobot.tenancy.models import ConfigRevision
from autobot.tenancy.registry import TenantSource, load_registry, sources_from_database
from autobot.tenancy.store.errors import StoreError, validated_document, validation_error
from packs import registry as packs_registry

INVALID = "La configuración no es válida"


def current_sources(alias: str = "owner") -> list[TenantSource]:
    return sources_from_database(alias)[1]


def find_source(slug: str, sources: list[TenantSource]) -> TenantSource:
    for source in sources:
        if isinstance(source.document, dict) and source.document.get("slug") == slug:
            return source
    raise StoreError("not_found", "No se encuentra el negocio")


def lock() -> ConfigRevision:
    return ConfigRevision.objects.using("owner").select_for_update().get(pk=1)


def _calendar_key(document: Mapping[str, Any]) -> str | None:
    config = document.get("config")
    value = config.get("calendar_id") if isinstance(config, dict) else None
    # Google calendar ids are e-mail-like, so case does not distinguish them.
    return value.strip().lower() if isinstance(value, str) and value.strip() else None


def _reject_shared_calendar(document: Mapping[str, Any], others: list[TenantSource]) -> None:
    """Two businesses on one Google calendar would book over each other's events and
    read each other's appointments: refuse it at save time. Offboarded businesses no
    longer use theirs, so they do not count."""
    mine = _calendar_key(document)
    if mine is None or document.get("status") == "offboarded":
        return
    for other in others:
        other_doc = other.document
        if (
            isinstance(other_doc, dict)
            and other_doc.get("status") != "offboarded"
            and _calendar_key(other_doc) == mine
        ):
            raise StoreError(
                "validation_error", INVALID, ["config.calendar_id: ya lo usa otro negocio"]
            )


def _check_pack_config(document: dict[str, Any]) -> None:
    pack = packs_registry.PACKS.get(document["pack"])
    if pack is None:
        raise StoreError("validation_error", INVALID, ["pack: pack no disponible"])
    try:
        pack.config_schema.model_validate(document["config"])
    except ValidationError as error:
        raise validation_error(error, "config.") from None


def _check_registry(slug: str, candidates: list[TenantSource]) -> None:
    """Load the registry as it would be with the candidate and refuse it if the
    candidate comes out degraded, ambiguous or rejected."""
    registry = load_registry(candidates, packs_registry.PACKS)
    tenant = registry.by_slug.get(slug)
    if slug in registry.errors or tenant is None:
        raise StoreError(
            "validation_error", "El documento no es válido", ["document: documento no válido"]
        )
    if tenant.is_degraded or tenant.ambiguous:
        duplicate = [
            name
            for name in ("id", "public_id", "phone_number_id")
            if f"{name} repeated" in tenant.degraded
        ]
        # Surface the real reason (e.g. a bus town missing from its dataset)
        # instead of a generic, unhelpful message.
        details = (
            [f"{name}: valor repetido" for name in duplicate]
            or [f"datasets: {reason}" for reason in tenant.degraded]
            or ["datasets: datos no válidos"]
        )
        raise StoreError("validation_error", INVALID, details)


def validate_candidate(source: TenantSource, sources: list[TenantSource]) -> None:
    document = validated_document(source.document)
    source = replace(source, document=document)
    if any(not isinstance(name, str) or not 1 <= len(name) <= 64 for name in source.datasets):
        raise StoreError(
            "validation_error", "Nombre de dataset no válido", ["datasets: nombre no válido"]
        )
    _check_pack_config(document)
    others = [
        s
        for s in sources
        if not isinstance(s.document, dict) or s.document.get("id") != document["id"]
    ]
    _reject_shared_calendar(document, others)
    _check_registry(document["slug"], [*others, source])
