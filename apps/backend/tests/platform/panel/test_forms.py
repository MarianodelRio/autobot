"""`document_schema`/`ui_schema` combine `TenantDocument` with each real pack's own
config schema; no DB needed, so this runs against `packs.registry.PACKS`
directly, not the `toy` pack the other panel tests monkeypatch in."""

from typing import Any

import jsonschema
import pytest
import yaml

from autobot.panel.services import forms
from packs.registry import PACKS


@pytest.mark.parametrize("pack_name", list(PACKS))
def test_document_schema_is_valid_json_schema(pack_name: str) -> None:
    # Draft-07, not 2020-12: the schema is reshaped for rjsf/ajv8, which render
    # and validate against draft-07 semantics (fixed-length `items` as an array, a
    # nullable field merged into `type: [X, "null"]`), not pydantic's own 2020-12 output.
    schema = forms.document_schema(pack_name)
    jsonschema.Draft7Validator.check_schema(schema)


@pytest.mark.parametrize("pack_name", list(PACKS))
def test_template_document_satisfies_its_own_schema(pack_name: str) -> None:
    pack = PACKS[pack_name]
    assert pack.template is not None
    raw = yaml.safe_load((pack.template / "document.yaml").read_text(encoding="utf-8"))
    schema = forms.document_schema(pack_name)
    jsonschema.Draft7Validator(schema).validate(raw)


@pytest.mark.parametrize("pack_name", list(PACKS))
def test_config_defs_are_prefixed_so_they_cannot_collide(pack_name: str) -> None:
    schema = forms.document_schema(pack_name)
    config_schema = schema["properties"]["config"]
    assert config_schema != {}
    # Every $ref under config points at a prefixed, now-merged definition.
    text = str(config_schema)
    if "$ref" in text:
        assert all(ref.startswith("#/$defs/pack_") for ref in _refs(config_schema))


def _refs(node: Any) -> list[str]:
    found: list[str] = []
    if isinstance(node, dict):
        if isinstance(node.get("$ref"), str):
            found.append(node["$ref"])
        for value in node.values():
            found.extend(_refs(value))
    elif isinstance(node, list):
        for value in node:
            found.extend(_refs(value))
    return found


def test_ui_schema_groups_and_read_only_fields() -> None:
    ui = forms.ui_schema("salon")
    assert [g["key"] for g in ui["groups"]] == ["business", "channel", "people", "legal", "config"]
    assert "channel.public_id" in ui["read_only"]
    assert set(ui["hidden"]) == {"id", "slug", "pack", "status"}
    assert set(ui["collapsed"]) == {"config.texts", "config.special_event"}


def test_salon_texts_and_info_text_get_a_textarea_widget() -> None:
    ui = forms.ui_schema("salon")
    assert ui["widgets"]["config.info_text"] == "textarea"
    assert ui["widgets"]["config.texts.welcome"] == "textarea"


def test_bus_has_no_textarea_widgets() -> None:
    assert forms.ui_schema("bus")["widgets"] == {"timezone": "timezone"}


def test_every_pack_gets_the_timezone_widget() -> None:
    assert forms.ui_schema("salon")["widgets"]["timezone"] == "timezone"
    assert forms.ui_schema("bus")["widgets"]["timezone"] == "timezone"


def test_salon_has_custom_fields_for_hours_and_services() -> None:
    ui = forms.ui_schema("salon")
    assert ui["fields"] == {
        "config.opening_hours": "OpeningHours",
        "config.services": "Services",
    }


def test_bus_has_no_custom_fields() -> None:
    assert forms.ui_schema("bus")["fields"] == {}


def test_list_packs_reports_datasets_and_template() -> None:
    by_name = {p.name: p for p in forms.list_packs()}
    assert by_name["bus"].has_datasets is True
    assert by_name["bus"].has_template is True
    assert by_name["bus"].dataset_names == ("timetable",)
    assert by_name["salon"].has_datasets is False
    assert by_name["salon"].has_template is True
    assert by_name["salon"].dataset_names == ()


def test_pack_template_blanks_the_salon_placeholders() -> None:
    config = forms.pack_template("salon")
    assert config is not None
    assert config["business_name"] is None
    assert config["contact_phone"] is None
    assert config["calendar_id"] is None
    assert config["info_text"] is None  # a new salon no longer inherits the demo's text
    assert config["services"]  # untouched fields stay filled in


def test_pack_template_blanks_the_bus_placeholders() -> None:
    # a new bus no longer inherits the demo's name, phone or towns.
    config = forms.pack_template("bus")
    assert config is not None
    assert config["business_name"] is None
    assert config["contact_phone"] is None
    assert config["start_menu_towns"] is None
    assert config["office_hours"]  # untouched fields stay filled in


def test_nullable_scalar_field_merges_into_a_type_array() -> None:
    # `str | None` (e.g. a WhatsApp Meta id) must render its own widget
    # directly, which rjsf only does for `type: [X, "null"]`, never `anyOf`.
    schema = forms.document_schema("salon")
    app_id = schema["$defs"]["WhatsAppChannel"]["properties"]["app_id"]
    assert "anyOf" not in app_id
    assert app_id["type"] == ["string", "null"]
    assert app_id["pattern"]  # the rest of the branch's schema survives


def test_nullable_ref_field_merges_into_a_type_array() -> None:
    # `Owner | None` must do the same, inlining the $ref.
    schema = forms.document_schema("salon")
    owner = schema["properties"]["owner"]
    assert "anyOf" not in owner
    assert owner["type"] == ["object", "null"]
    assert owner["title"] == "Dueño"
    assert "notify" in owner["properties"]


def test_discriminated_channel_union_is_left_alone() -> None:
    # The channel's own type selector (WhatsApp vs Telegram) must still work.
    schema = forms.document_schema("salon")
    channel = schema["properties"]["channel"]
    assert "anyOf" in channel
    assert channel["anyOf"][0]["discriminator"]["propertyName"] == "type"


def test_tuple_field_uses_fixed_items_rjsf_understands() -> None:
    # `reminder_window_hours: tuple[int, int]` must render as two number boxes,
    # which rjsf only does for draft-07 `items: [...]`, never 2020-12's `prefixItems`.
    schema = forms.document_schema("salon")
    window = schema["properties"]["config"]["properties"]["reminder_window_hours"]
    assert "prefixItems" not in window
    assert window["items"] == [{"type": "integer"}, {"type": "integer"}]
    assert window["additionalItems"] is False
    assert window["minItems"] == window["maxItems"] == 2


def test_owner_notify_is_restricted_to_the_packs_own_notices() -> None:
    # rjsf renders a checkbox list only once the array's items carry an enum.
    schema = forms.document_schema("salon")
    notify = schema["$defs"]["Owner"]["properties"]["notify"]
    assert notify["items"]["enum"] == [
        "booking_created",
        "booking_cancelled",
        "booking_moved",
        "move_cancel_failed",
    ]
    assert notify["items"]["enumNames"][0] == "Cita nueva"
    assert notify["uniqueItems"] is True


def test_bus_has_no_owner_notices_yet() -> None:
    schema = forms.document_schema("bus")
    notify = schema["$defs"]["Owner"]["properties"]["notify"]
    assert "enum" not in notify["items"]


def test_unknown_pack_is_not_found() -> None:
    from autobot.panel.errors import ApiError

    with pytest.raises(ApiError) as excinfo:
        forms.document_schema("nope")
    assert excinfo.value.status == 404
