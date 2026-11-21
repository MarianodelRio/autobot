"""Creating, publishing, rolling back and changing the status of a tenant's document."""

import copy
import secrets as random_secrets
import string
from collections.abc import Mapping
from dataclasses import replace
from typing import Any, Literal
from uuid import uuid7

from django.db import transaction

from autobot.tenancy.models import Tenant, TenantDocumentVersion
from autobot.tenancy.registry import TenantSource
from autobot.tenancy.store import validate
from autobot.tenancy.store.channel_secrets import secrets_for, write_secret
from autobot.tenancy.store.datasets import LibraryOrigin, write_dataset
from autobot.tenancy.store.errors import StoreError, identity_changed, validated_document
from autobot.tenancy.store.revision import write_document
from packs import registry as packs_registry

# What a rollback restores from the old version; everything else keeps its current value.
CONTENT_KEYS = ("name", "timezone", "config")

TRANSITIONS: dict[str, tuple[set[str], str]] = {
    "activate": ({"onboarding"}, "active"),
    "pause": ({"active"}, "paused"),
    "resume": ({"paused"}, "active"),
    "offboard": ({"active", "paused", "onboarding"}, "offboarded"),
}


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
    pack_obj = packs_registry.PACKS.get(pack)
    doc: dict[str, Any] = {
        "id": str(uuid7()),
        "slug": slug,
        "name": name,
        "timezone": timezone,
        "pack": pack,
        "config": copy.deepcopy(config),
        "status": "paused" if demo_description is not None else "onboarding",
        # Every notice the pack can emit, on by default, same as the demo;
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
        doc["channel"] = _new_channel(channel_type)
        doc["testers"] = {"main": []}
    else:
        raise StoreError("bad_request", "El negocio necesita un canal o una descripción de demo")
    return doc


def _new_channel(channel_type: Literal["whatsapp", "telegram"]) -> dict[str, Any]:
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
    return channel


def _check_new_tenant(doc: dict[str, Any], datasets: Mapping[str, Any] | None) -> None:
    if TenantDocumentVersion.objects.using("owner").filter(tenant_id=doc["id"]).exists():
        raise StoreError("conflict", "El negocio ya tiene configuración")
    if Tenant.objects.using("owner").filter(slug=doc["slug"]).exclude(pk=doc["id"]).exists():
        raise StoreError("conflict", "El slug ya existe")
    pack = packs_registry.PACKS.get(doc["pack"])
    # A pack that needs datasets (e.g. bus's timetable) must have one chosen
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


@transaction.atomic(using="owner")
def create_tenant(
    *,
    document: dict[str, Any],
    datasets: Mapping[str, Mapping[str, str]] | None = None,
    dataset_origins: Mapping[str, LibraryOrigin] | None = None,
    secrets: Mapping[str, str] | None = None,
    actor: str,
    comment: str,
    keep_status: bool = False,
) -> int:
    revision = validate.lock()
    raw = copy.deepcopy(document)
    if not keep_status:
        raw["status"] = "paused" if raw.get("demo") is not None else "onboarding"
    doc = validated_document(raw)
    _check_new_tenant(doc, datasets)
    raw_secrets = secrets_for(doc, secrets)
    source = TenantSource(doc["slug"], doc, datasets=datasets or {}, secrets=raw_secrets)
    validate.validate_candidate(source, validate.current_sources())
    version = write_document(
        source,
        revision,
        actor=actor,
        comment=comment,
        action="tenant.create",
        summary="Negocio creado",
    )
    if raw_secrets is not None:
        write_secret(source, raw_secrets, actor)
    for name, files in (datasets or {}).items():
        origin = (dataset_origins or {}).get(name)
        write_dataset(source, name, files, actor=actor, comment=comment, library_origin=origin)
    return version


@transaction.atomic(using="owner")
def publish(
    slug: str, *, document: dict[str, Any], base_version: int, actor: str, comment: str
) -> int:
    revision = validate.lock()
    sources = validate.current_sources()
    current = validate.find_source(slug, sources)
    if current.version != base_version:
        raise StoreError("conflict", "Hay una versión más reciente; recarga la configuración")
    doc = validated_document(document)
    if identity_changed(doc, current.document):
        raise StoreError(
            "forbidden_change",
            "La publicación no permite cambiar la identidad, el estado o el tipo de canal",
        )
    candidate = replace(current, document=doc)
    validate.validate_candidate(candidate, sources)
    return write_document(
        candidate,
        revision,
        actor=actor,
        comment=comment,
        action="tenant.publish",
        summary="Configuración publicada",
    )


@transaction.atomic(using="owner")
def rollback(slug: str, *, version: int, actor: str, comment: str) -> int:
    revision = validate.lock()
    sources = validate.current_sources()
    current = validate.find_source(slug, sources)
    previous = (
        TenantDocumentVersion.objects.using("owner")
        .filter(tenant_id=current.document["id"], version=version)
        .first()
    )
    if previous is None:
        raise StoreError("not_found", "No se encuentra la versión")
    # A rollback restores only the editable content. Identity, status, the whole
    # channel (its Meta ids, display phone and thresholds are operational state
    # tied to the live number), testers, owner and demo info stay as they are now:
    # going back to a version from before WhatsApp was connected must not
    # disconnect the number.
    previous_doc = previous.document
    doc = copy.deepcopy(current.document)
    for key in CONTENT_KEYS:
        if key in previous_doc:
            doc[key] = copy.deepcopy(previous_doc[key])
    candidate = replace(current, document=validated_document(doc))
    validate.validate_candidate(candidate, sources)
    return write_document(
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
    from autobot.tenancy import activation  # it reads the store back: a real cycle

    if action not in TRANSITIONS:
        raise StoreError("bad_request", "Acción de estado no válida")
    if action in ("activate", "offboard") and confirm_slug != slug:
        raise StoreError("bad_request", "Escribe el slug para confirmar")
    if action == "activate":
        before = validate.find_source(slug, validate.current_sources())
        if before.document.get("status") != "onboarding" or before.document.get("demo") is not None:
            raise StoreError("invalid_status", "El estado no permite esta acción")
        if activation.checklist(slug).blocking:
            raise StoreError("bad_request", "La activación tiene comprobaciones pendientes")
    with transaction.atomic(using="owner"):
        revision = validate.lock()
        sources = validate.current_sources()
        current = validate.find_source(slug, sources)
        allowed, status = TRANSITIONS[action]
        if current.document["status"] not in allowed:
            raise StoreError("invalid_status", "El estado no permite esta acción")
        candidate = replace(
            current, document=validated_document({**current.document, "status": status})
        )
        if action not in ("pause", "offboard"):
            # Pausing and offboarding must always be possible, even for a tenant
            # degraded for a reason unrelated to this change: they change
            # nothing else, so there is nothing new to validate, and they are
            # precisely the way to take a broken tenant out of service.
            validate.validate_candidate(candidate, sources)
        return write_document(
            candidate,
            revision,
            actor=actor,
            comment=action,
            action="tenant.status",
            summary=f"Estado cambiado a {status}",
        )
