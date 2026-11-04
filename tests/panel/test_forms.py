"""`document_schema`/`ui_schema` combine `TenantDocument` with each real pack's own
config schema (DESIGN §9.5); no DB needed, so this runs against `packs.registry.PACKS`
directly, not the `toy` pack the other panel tests monkeypatch in."""

from typing import Any

import jsonschema
import pytest
import yaml

from autobot.panel.services import forms
from packs.registry import PACKS


@pytest.mark.parametrize("pack_name", list(PACKS))
def test_document_schema_is_valid_json_schema(pack_name: str) -> None:
    schema = forms.document_schema(pack_name)
    jsonschema.Draft202012Validator.check_schema(schema)


@pytest.mark.parametrize("pack_name", list(PACKS))
def test_template_document_satisfies_its_own_schema(pack_name: str) -> None:
    pack = PACKS[pack_name]
    assert pack.template is not None
    raw = yaml.safe_load((pack.template / "document.yaml").read_text(encoding="utf-8"))
    schema = forms.document_schema(pack_name)
    jsonschema.validate(instance=raw, schema=schema)


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
    assert [g["key"] for g in ui["groups"]] == ["general", "channel", "config"]
    assert "channel.public_id" in ui["read_only"]


def test_salon_texts_and_info_text_get_a_textarea_widget() -> None:
    ui = forms.ui_schema("salon")
    assert ui["widgets"]["config.info_text"] == "textarea"
    assert ui["widgets"]["config.texts.welcome"] == "textarea"


def test_bus_has_no_textarea_widgets() -> None:
    assert forms.ui_schema("bus")["widgets"] == {}


def test_list_packs_reports_datasets_and_template() -> None:
    by_name = {p.name: p for p in forms.list_packs()}
    assert by_name["bus"].has_datasets is True
    assert by_name["bus"].has_template is True
    assert by_name["salon"].has_datasets is False
    assert by_name["salon"].has_template is True


def test_pack_template_blanks_the_salon_placeholders() -> None:
    config = forms.pack_template("salon")
    assert config is not None
    assert config["business_name"] is None
    assert config["contact_phone"] is None
    assert config["calendar_id"] is None
    assert config["services"]  # untouched fields stay filled in


def test_bus_template_has_no_blanked_fields() -> None:
    config = forms.pack_template("bus")
    assert config is not None
    assert config["business_name"] is not None


def test_unknown_pack_is_not_found() -> None:
    from autobot.panel.errors import ApiError

    with pytest.raises(ApiError) as excinfo:
        forms.document_schema("nope")
    assert excinfo.value.status == 404
