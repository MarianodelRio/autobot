"""Packs and the generated form of a tenant document (DESIGN §6.4, §9.5)."""

import copy
from dataclasses import dataclass
from typing import Any

import yaml
from ninja import Schema

from autobot.panel.errors import ApiError
from autobot.tenancy.schema import TenantDocument


@dataclass(frozen=True)
class PackSummary:
    name: str
    has_datasets: bool
    has_template: bool


class PackOut(Schema):
    name: str
    has_datasets: bool
    has_template: bool


class PackSchemaOut(Schema):
    document: dict[str, Any]
    ui_schema: dict[str, Any]


class PackTemplateOut(Schema):
    config: dict[str, Any] | None


GENERAL_FIELDS = ["id", "slug", "name", "status", "timezone", "pack", "testers", "owner", "demo"]
GROUPS: tuple[tuple[str, str, list[str]], ...] = (
    ("general", "General", GENERAL_FIELDS),
    ("channel", "Canal", ["channel"]),
    ("config", "Config del pack", ["config"]),
)
READ_ONLY = ("id", "slug", "pack", "status", "channel.type", "channel.public_id")


def _pack(name: str) -> Any:
    from packs.registry import PACKS

    pack = PACKS.get(name)
    if pack is None:
        raise ApiError("not_found", "No se encuentra el pack", 404)
    return pack


def list_packs() -> list[PackSummary]:
    from packs.registry import PACKS

    return [
        PackSummary(
            name=p.name, has_datasets=p.load_data is not None, has_template=p.template is not None
        )
        for p in PACKS.values()
    ]


def _prefix_refs(node: Any, prefix: str) -> Any:
    """Rewrite every `#/$defs/X` into `#/$defs/<prefix>X`, recursively."""
    if isinstance(node, dict):
        out = {k: _prefix_refs(v, prefix) for k, v in node.items()}
        ref = out.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/$defs/"):
            out["$ref"] = ref.replace("#/$defs/", f"#/$defs/{prefix}", 1)
        return out
    if isinstance(node, list):
        return [_prefix_refs(v, prefix) for v in node]
    return node


def document_schema(pack_name: str) -> dict[str, Any]:
    """`TenantDocument.model_json_schema()`, with `config` replaced by the pack's own
    schema; both sets of `$defs` are merged under distinct prefixes so they never
    collide (DESIGN §9.5)."""
    pack = _pack(pack_name)
    document = TenantDocument.model_json_schema()
    config = pack.config_schema.model_json_schema()
    config_defs = config.pop("$defs", {})
    config = _prefix_refs(config, "pack_")
    config_defs = {
        f"pack_{name}": _prefix_refs(definition, "pack_")
        for name, definition in config_defs.items()
    }
    document.setdefault("$defs", {}).update(config_defs)
    document["properties"]["config"] = config
    return document


def _textarea_fields(pack: Any) -> list[str]:
    fields = pack.config_schema.model_fields
    widgets = []
    if "info_text" in fields:
        widgets.append("config.info_text")
    texts = fields.get("texts")
    if texts is not None:
        texts_fields = getattr(texts.annotation, "model_fields", {})
        widgets.extend(f"config.texts.{name}" for name in texts_fields)
    return widgets


def ui_schema(pack_name: str) -> dict[str, Any]:
    pack = _pack(pack_name)
    return {
        "groups": [{"key": key, "label": label, "fields": fields} for key, label, fields in GROUPS],
        "read_only": list(READ_ONLY),
        "widgets": {field: "textarea" for field in _textarea_fields(pack)},
    }


def pack_template(pack_name: str) -> dict[str, Any] | None:
    """The demo document's `config`, with `Pack.template_blank` fields cleared, ready
    to seed a new tenant's form."""
    pack = _pack(pack_name)
    if pack.template is None:
        return None
    document_path = pack.template / "document.yaml"
    if not document_path.is_file():
        document_path = pack.template / "tenant.yaml"
    raw = yaml.safe_load(document_path.read_text(encoding="utf-8"))
    config: dict[str, Any] = copy.deepcopy(raw.get("config", {}))
    for field in pack.template_blank:
        config[field] = None
    return config
