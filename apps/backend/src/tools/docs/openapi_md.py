"""Render the panel's OpenAPI schema (`apps/panel/openapi.json`) as a Markdown reference.

Run from the repo root: `python -m tools.docs.openapi_md` (from `apps/backend/src`), which
rewrites `docs/referencia/api-panel.md`; `make api` does it after exporting the schema.
`--check` exits 1 if the file is out of date. The output is deterministic: tags, paths and
fields are sorted.
"""

import argparse
import json
import sys
from typing import Any

from tools._paths import REPO_ROOT

__all__ = ["main", "render"]

SCHEMA_PATH = REPO_ROOT / "apps" / "panel" / "openapi.json"
OUTPUT_PATH = REPO_ROOT / "docs" / "referencia" / "api-panel.md"
API_PREFIX = "/api/panel"
METHODS = ("get", "post", "put", "patch", "delete")

HEADER = """\
# API del panel

<!-- Generado por apps/backend/src/tools/docs/openapi_md.py desde apps/panel/openapi.json.
     No editar: ejecuta `make api`. -->

!!! warning "Generado, no editar"
    Esta página sale de `apps/panel/openapi.json` con `make api`. Si hay que cambiarla,
    se cambia el código del router y se regenera.

Referencia de la API interna del panel. Léela para saber qué endpoints hay y qué reciben y
devuelven. Todas las rutas cuelgan de `{prefix}` y solo son accesibles por túnel SSH
(ADR-008). Salvo `GET /auth/csrf` y `POST /auth/login`, exigen la cookie de sesión
`autobot_panel_session`; las peticiones que modifican datos exigen además el token CSRF.
Cómo se organiza el panel está en [panel](../arquitectura/panel.md).
"""


def _ref_name(ref: str) -> str:
    return ref.rsplit("/", 1)[-1]


def _type(schema: dict[str, Any] | None) -> str:
    """Short, readable type of a JSON schema (refs are shown by name)."""
    if not schema:
        return "any"
    if "$ref" in schema:
        return _ref_name(schema["$ref"])
    for key in ("anyOf", "oneOf"):
        if key in schema:
            return " | ".join(_type(option) for option in schema[key])
    if "enum" in schema:
        return " | ".join(json.dumps(value) for value in schema["enum"])
    kind = schema.get("type", "any")
    if kind == "array":
        return f"{_type(schema.get('items'))}[]"
    if kind == "string" and "format" in schema:
        return f"string ({schema['format']})"
    return str(kind)


def _body_schema(operation: dict[str, Any]) -> dict[str, Any] | None:
    content = operation.get("requestBody", {}).get("content", {})
    media = content.get("application/json") or next(iter(content.values()), None)
    return media.get("schema") if media else None


def _response_type(operation: dict[str, Any]) -> str:
    for code in sorted(operation.get("responses", {})):
        if code.startswith("2"):
            content = operation["responses"][code].get("content", {})
            media = content.get("application/json") or next(iter(content.values()), None)
            return _type(media.get("schema")) if media else "sin cuerpo"
    return "sin cuerpo"


def _fields(schema: dict[str, Any] | None, schemas: dict[str, Any]) -> list[str]:
    """`name: type` for each property of an object schema (a ref is resolved one level)."""
    if schema is None:
        return []
    if "$ref" in schema:
        schema = schemas.get(_ref_name(schema["$ref"]), {})
    required = set(schema.get("required", []))
    return [
        f"`{name}`{'' if name in required else ' (opcional)'}: {_type(prop)}"
        for name, prop in sorted(schema.get("properties", {}).items())
    ]


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def _operation_lines(
    method: str, path: str, operation: dict[str, Any], schemas: dict[str, Any]
) -> list[str]:
    parameters = sorted(
        operation.get("parameters", []), key=lambda p: (p["in"] != "path", p["name"])
    )
    params = [
        f"`{p['name']}` ({p['in']}{', obligatorio' if p.get('required') else ''}): "
        f"{_type(p.get('schema'))}"
        for p in parameters
    ]
    body = _body_schema(operation)
    body_name = _type(body) if body else None
    lines: list[str] = []
    if not params and body is None:
        return lines
    lines.append(f"- `{method.upper()} {API_PREFIX}{path}`")
    for param in params:
        lines.append(f"    - Parámetro {param}")
    if body_name is not None:
        optional = "" if operation["requestBody"].get("required") else " (opcional)"
        lines.append(f"    - Cuerpo{optional}: {body_name}")
        for field in _fields(body, schemas):
            lines.append(f"        - {field}")
    return lines


def render(schema: dict[str, Any]) -> str:
    schemas = schema.get("components", {}).get("schemas", {})
    by_tag: dict[str, list[tuple[str, str, dict[str, Any]]]] = {}
    for path, item in schema["paths"].items():
        for method in METHODS:
            operation = item.get(method)
            if operation is None:
                continue
            for tag in operation.get("tags") or ["sin etiqueta"]:
                by_tag.setdefault(tag, []).append((path, method, operation))

    out = [HEADER.format(prefix=API_PREFIX)]
    for tag in sorted(by_tag):
        operations = sorted(by_tag[tag], key=lambda o: (o[0], METHODS.index(o[1])))
        out.append(f"## {tag}\n")
        out.append("| Método | Ruta | Resumen | Respuesta |")
        out.append("| --- | --- | --- | --- |")
        for path, method, operation in operations:
            out.append(
                f"| {method.upper()} | `{API_PREFIX}{path}` | "
                f"{_cell(operation.get('summary', ''))} | {_cell(_response_type(operation))} |"
            )
        detail = [
            line
            for path, method, operation in operations
            for line in _operation_lines(method, path, operation, schemas)
        ]
        if detail:
            out.append("\nParámetros y cuerpos:\n")
            out.extend(detail)
        out.append("")
    return "\n".join(out).rstrip("\n") + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail if the output is stale")
    args = parser.parse_args(argv)
    content = render(json.loads(SCHEMA_PATH.read_text(encoding="utf-8")))
    if args.check:
        current = OUTPUT_PATH.read_text(encoding="utf-8") if OUTPUT_PATH.exists() else ""
        if current != content:
            print(f"{OUTPUT_PATH} is stale: run `make api`.", file=sys.stderr)
            return 1
        return 0
    OUTPUT_PATH.write_text(content, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
