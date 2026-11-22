"""Packs and the generated form of a tenant document."""

import copy
from dataclasses import dataclass
from typing import Any, cast

import yaml
from ninja import Schema

from autobot.panel.errors import ApiError
from autobot.tenancy import dataset_library
from autobot.tenancy.registry import source_from_dir
from autobot.tenancy.schema import TenantDocument
from packs import registry as pack_registry  # read `PACKS` at call time: tests replace it


@dataclass(frozen=True)
class PackSummary:
    name: str
    has_datasets: bool
    has_template: bool
    dataset_names: tuple[str, ...] = ()


class PackOut(Schema):
    name: str
    has_datasets: bool
    has_template: bool
    dataset_names: list[str]


class PackSchemaOut(Schema):
    document: dict[str, Any]
    ui_schema: dict[str, Any]


class PackTemplateOut(Schema):
    config: dict[str, Any] | None


class LibraryEntryOut(Schema):
    name: str
    version: int
    summary: dict[str, Any]
    author: str
    comment: str
    created_at: Any


def dataset_library_entries(pack_name: str, dataset: str) -> list[LibraryEntryOut]:
    """The alta's and the ficha's picker: every named entry's latest
    version for this pack's dataset, never the raw files."""
    _pack(pack_name)  # 404 for an unknown pack
    return [
        LibraryEntryOut(
            name=entry.name,
            version=entry.version,
            summary=entry.summary,
            author=entry.author,
            comment=entry.comment,
            created_at=entry.created_at,
        )
        for entry in dataset_library.list_entries(pack_name, dataset)
    ]


GROUPS: tuple[tuple[str, str, list[str]], ...] = (
    ("business", "Negocio", ["name", "timezone", "demo"]),
    ("channel", "Canal", ["channel"]),
    ("people", "Dueño y testers", ["owner", "testers"]),
    ("legal", "Privacidad y atención", ["privacy", "support"]),
    ("config", "Ajustes del pack", ["config"]),
)
HIDDEN = ("id", "slug", "pack", "status")
COLLAPSED = ("config.texts", "config.special_event")
READ_ONLY = ("id", "slug", "pack", "status", "channel.type", "channel.public_id")


def _pack(name: str) -> Any:
    pack = pack_registry.PACKS.get(name)
    if pack is None:
        raise ApiError("not_found", "No se encuentra el pack", 404)
    return pack


def _template_dataset_names(pack: Any) -> tuple[str, ...]:
    """The dataset names a pack's own template declares: the alta's picker
    needs these to know which library datasets to ask for, since a pack's own
    directory layout is the only canonical source of them."""
    if pack.template is None:
        return ()
    source = source_from_dir(pack.template)
    return tuple(sorted(source.datasets))


def list_packs() -> list[PackSummary]:
    return [
        PackSummary(
            name=p.name,
            has_datasets=p.load_data is not None,
            has_template=p.template is not None,
            dataset_names=_template_dataset_names(p),
        )
        for p in pack_registry.PACKS.values()
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


_NULL_SCHEMA = {"type": "null"}


def _merge_nullable(node: Any, defs: dict[str, Any]) -> Any:
    """rjsf only renders a nullable field's own widget directly (no branch selector)
    when the schema uses `"type": [X, "null"]`, not `anyOf`/`oneOf` (`str | None`
    and `Owner | None` fields had no input box). Merges a plain `anyOf: [<schema>,
    {"type": "null"}]` into one node; a discriminated union (`channel: Channel | None`)
    is left alone, since it needs its own branch selection."""
    if isinstance(node, dict):
        out = {key: _merge_nullable(value, defs) for key, value in node.items()}
        any_of = out.get("anyOf")
        if isinstance(any_of, list) and len(any_of) == 2 and _NULL_SCHEMA in any_of:
            other = next(branch for branch in any_of if branch != _NULL_SCHEMA)
            if isinstance(other, dict) and not any(
                key in other for key in ("oneOf", "anyOf", "discriminator")
            ):
                resolved = (
                    copy.deepcopy(defs[other["$ref"].removeprefix("#/$defs/")])
                    if set(other) == {"$ref"}
                    else copy.deepcopy(other)
                )
                kind = resolved.get("type", "object" if "properties" in resolved else "string")
                own = {key: value for key, value in out.items() if key != "anyOf"}
                out = {**resolved, **own, "type": [kind, "null"]}
        return out
    if isinstance(node, list):
        return [_merge_nullable(value, defs) for value in node]
    return node


def _fixed_items(node: Any) -> Any:
    """rjsf only recognizes a fixed-length tuple (`isFixedItems`) as the draft-07
    `items: [<schema>, ...]`, never 2020-12's `prefixItems` that pydantic emits for a
    `tuple[int, int]` (`reminder_window_hours` had no usable widget)."""
    if isinstance(node, dict):
        out = {key: _fixed_items(value) for key, value in node.items()}
        prefix_items = out.pop("prefixItems", None)
        if isinstance(prefix_items, list):
            out["items"] = prefix_items
            out.setdefault("additionalItems", False)
        return out
    if isinstance(node, list):
        return [_fixed_items(value) for value in node]
    return node


def _owner_notice_checkboxes(document: dict[str, Any], pack: Any) -> None:
    """`owner.notify` is a plain `list[str]` in the schema (any pack's kinds fit
    the same field); restricting its items to this pack's own declared
    `owner_notices`, with `enumNames` for their labels, is what makes rjsf render it
    as a list of checkboxes instead of a free-text, reorderable array."""
    notify = document.get("$defs", {}).get("Owner", {}).get("properties", {}).get("notify")
    if not isinstance(notify, dict) or not pack.owner_notices:
        return
    notify["items"] = {
        "type": "string",
        "enum": [notice.kind for notice in pack.owner_notices],
        "enumNames": [notice.label for notice in pack.owner_notices],
    }
    notify["uniqueItems"] = True


def document_schema(pack_name: str) -> dict[str, Any]:
    """`TenantDocument.model_json_schema()`, with `config` replaced by the pack's own
    schema; both sets of `$defs` are merged under distinct prefixes so they never
    collide."""
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
    _owner_notice_checkboxes(document, pack)
    return cast("dict[str, Any]", _fixed_items(_merge_nullable(document, document["$defs"])))


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


CUSTOM_FIELDS: dict[str, dict[str, str]] = {
    # A dedicated per-day editor and a table with an automatic id, instead of
    # rjsf's generic dict/array widgets.
    "salon": {"config.opening_hours": "OpeningHours", "config.services": "Services"},
}


def ui_schema(pack_name: str) -> dict[str, Any]:
    pack = _pack(pack_name)
    return {
        "groups": [{"key": key, "label": label, "fields": fields} for key, label, fields in GROUPS],
        "read_only": list(READ_ONLY),
        "hidden": list(HIDDEN),
        "collapsed": list(COLLAPSED),
        "fields": CUSTOM_FIELDS.get(pack_name, {}),
        "widgets": {
            **{field: "textarea" for field in _textarea_fields(pack)},
            "timezone": "timezone",
        },
    }


def pack_template(pack_name: str) -> dict[str, Any] | None:
    """The demo document's `config`, with `Pack.template_blank` fields cleared, ready
    to seed a new tenant's form."""
    pack = _pack(pack_name)
    if pack.template is None:
        return None
    document_path = pack.template / "document.yaml"
    raw = yaml.safe_load(document_path.read_text(encoding="utf-8"))
    config: dict[str, Any] = copy.deepcopy(raw.get("config", {}))
    for field in pack.template_blank:
        config[field] = None
    return config
