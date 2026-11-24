"""Packs and the generated form of a tenant document."""

import copy
from dataclasses import dataclass
from typing import Any, cast

import yaml
from ninja import Schema

from autobot.ops.runbooks import docs_url
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


@dataclass(frozen=True)
class Section:
    """One collapsible section of the Configuración tab. `fields` and `summary` are
    dotted paths into the document (`config.services`); a path the pack does not have
    is skipped, so the platform sections can name the fields every pack shares. The
    setup steps say which section they belong to (`SetupStepOut.section`)."""

    key: str
    label: str
    description: str
    fields: tuple[str, ...]
    summary: tuple[str, ...] = ()
    # The `docs/`-relative page (and `#anchor`) with the long explanation: the panel
    # links it as «Más información». `test_forms.py` checks the page and anchor exist.
    docs: str = ""


PLATFORM_SECTIONS: tuple[Section, ...] = (
    Section(
        "business",
        "Negocio",
        "Cómo se llama el negocio, en qué zona horaria trabaja y el teléfono que el bot"
        " da a sus clientes.",
        ("name", "timezone", "config.business_name", "config.contact_phone", "demo"),
        summary=("name", "timezone"),
        docs="procedimientos/alta-baja-negocio.md#alta",
    ),
    Section(
        "channel",
        "Canal",
        "Por dónde le escriben los clientes (WhatsApp o Telegram): los ids del proveedor,"
        " las credenciales, el enlace público y el QR.",
        ("channel",),
        summary=("channel.type", "channel.display_phone", "channel.bot_username"),
        docs="procedimientos/alta-baja-negocio.md#alta",
    ),
    Section(
        "people",
        "Dueño y testers",
        "El dueño recibe avisos y resúmenes en su propio chat. Los testers son los únicos"
        " que pueden escribir al bot mientras el negocio está en alta.",
        ("owner", "testers"),
        docs="arquitectura/bot-de-duenos.md",
    ),
    Section(
        "legal",
        "Privacidad y atención",
        "Lo que el bot dice en su primer mensaje sobre los datos personales y a quién"
        " acudir para hablar con una persona (al escribir PERSONA). Es obligatorio para"
        " activar.",
        ("privacy", "support"),
        summary=("privacy.policy_url", "support.human_contact"),
        docs="cumplimiento/informacion-al-interesado.md",
    ),
)
# The pack's own sections, after the platform's. A `config` field no section lists
# still shows, in a final «Otros ajustes» section the panel adds on its own.
PACK_SECTIONS: dict[str, tuple[Section, ...]] = {
    "salon": (
        Section(
            "services",
            "Servicios y horario",
            "Qué se puede reservar, cuándo abre el negocio y qué días cierra.",
            ("config.services", "config.opening_hours", "config.holidays", "config.info_text"),
            summary=("config.services",),
            docs="referencia/packs/salon.md#servicios",
        ),
        Section(
            "bookings",
            "Reservas y recordatorios",
            "Las reglas de las citas: cada cuánto empieza un hueco, con cuánta antelación"
            " se reserva, cuántas citas puede tener cada cliente y los recordatorios.",
            (
                "config.slot_step_min",
                "config.min_notice_min",
                "config.booking_window_days",
                "config.max_active_bookings",
                "config.reminders_enabled",
                "config.reminder_window_hours",
                "config.manual_confirmations_enabled",
                "config.manual_confirmations_since",
            ),
            summary=("config.booking_window_days", "config.reminders_enabled"),
            docs="referencia/packs/salon.md#configuracion",
        ),
        Section(
            "calendar",
            "Calendario de Google",
            "Las citas se guardan en el calendario del propio negocio, que debe compartirse"
            " con la cuenta de servicio de la plataforma.",
            ("config.calendar_id",),
            summary=("config.calendar_id",),
            docs="referencia/packs/salon.md#el-calendario",
        ),
        Section(
            "special_event",
            "Evento especial",
            "Un periodo con condiciones propias (por ejemplo, una campaña o unas fiestas).",
            ("config.special_event",),
            docs="referencia/packs/salon.md#evento-especial",
        ),
        Section(
            "texts",
            "Textos del bot",
            "Las frases que el bot usa en cada situación. Solo hace falta tocarlas para"
            " personalizar el tono.",
            ("config.texts",),
            docs="referencia/packs/salon.md#textos",
        ),
    ),
    "bus": (
        Section(
            "office",
            "Oficina y enlaces",
            "El horario de atención de la oficina y los enlaces a la web, la compra online,"
            " los bonos y los horarios en PDF.",
            ("config.office_hours", "config.links"),
            docs="referencia/packs/bus.md#configuracion",
        ),
        Section(
            "datasets",
            "Horarios y búsqueda",
            "Los horarios que consulta el bot (de la biblioteca), las localidades del menú"
            " inicial y cómo busca el próximo autobús.",
            (
                "config.start_menu_towns",
                "config.next_day_search_days",
                "config.schedule_disclaimer",
            ),
            summary=("config.start_menu_towns",),
            docs="referencia/packs/bus.md#dataset-de-horarios",
        ),
    ),
}
# A field shown only while the checkbox it depends on is on.
SHOW_IF: dict[str, str] = {
    "config.reminder_window_hours": "config.reminders_enabled",
    "config.manual_confirmations_since": "config.manual_confirmations_enabled",
}
HIDDEN = ("id", "slug", "pack", "status")
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
    sections = (*PLATFORM_SECTIONS, *PACK_SECTIONS.get(pack_name, ()))
    return {
        "groups": [
            {
                "key": s.key,
                "label": s.label,
                "description": s.description,
                "fields": list(s.fields),
                "summary": list(s.summary),
                "docs": docs_url(s.docs) if s.docs else None,
            }
            for s in sections
        ],
        "show_if": dict(SHOW_IF),
        "read_only": list(READ_ONLY),
        "hidden": list(HIDDEN),
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
