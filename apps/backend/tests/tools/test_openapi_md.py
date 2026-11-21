"""`docs/referencia/api-panel.md` is generated from `apps/panel/openapi.json`."""

import json

from tools.docs.openapi_md import OUTPUT_PATH, SCHEMA_PATH, render


def test_api_reference_is_up_to_date() -> None:
    expected = render(json.loads(SCHEMA_PATH.read_text(encoding="utf-8")))
    assert OUTPUT_PATH.read_text(encoding="utf-8") == expected, (
        "docs/referencia/api-panel.md is stale: run `make api`"
    )


def test_render_is_deterministic_and_covers_every_path() -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    first = render(schema)
    assert first == render(schema)
    for path in schema["paths"]:
        assert f"`/api/panel{path}`" in first
