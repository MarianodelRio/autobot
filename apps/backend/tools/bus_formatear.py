"""tools/bus_formatear.py — make bus-formatear TENANT=<slug>.

Realinea las columnas de los bloques
`tabla: |` de `lineas/*.yaml` del dataset del tenant a
nivel de texto, sin volcar el YAML de nuevo (para no tocar comentarios, orden
de claves ni nada más del fichero). Es idempotente: ejecutarlo dos veces
seguidas no cambia nada.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from tools.bus_tenant import REPO_ROOT, TenantDesconocido, dataset_dir

_TABLA_INICIO_RE = re.compile(r"^(?P<indent>[ \t]*)tabla:\s*\|\s*$")


def _indentacion(linea: str) -> int:
    return len(linea) - len(linea.lstrip(" \t"))


def _realinear_bloque(lineas_bloque: list[str], indent: str) -> list[str]:
    """Realinea un bloque de líneas de tabla (sin la línea 'tabla: |')."""
    filas_tokens: list[list[str] | None] = []  # None para líneas de comentario
    comentarios: dict[int, str] = {}
    restos: list[str] = []  # texto tras "|" en cada fila (incluye "-> obs Pnn" o "")

    for linea in lineas_bloque:
        contenido = linea.strip()
        if contenido.startswith("#"):
            filas_tokens.append(None)
            comentarios[len(filas_tokens) - 1] = contenido
            restos.append("")
            continue
        if "|" in contenido:
            izquierda, derecha = contenido.split("|", 1)
            filas_tokens.append(izquierda.split())
            restos.append(derecha.strip())
        else:
            filas_tokens.append(contenido.split())
            restos.append("")

    columnas = max((len(f) for f in filas_tokens if f is not None), default=0)
    anchos = [0] * columnas
    for fila in filas_tokens:
        if fila is None:
            continue
        for i, tok in enumerate(fila):
            anchos[i] = max(anchos[i], len(tok))

    salida: list[str] = []
    for idx, fila in enumerate(filas_tokens):
        if fila is None:
            salida.append(f"{indent}{comentarios[idx]}")
            continue
        partes = [tok.ljust(anchos[i]) for i, tok in enumerate(fila)]
        texto = "  ".join(partes).rstrip()
        if restos[idx]:
            texto = f"{texto}  | {restos[idx]}"
        salida.append(f"{indent}{texto}")
    return salida


def formatear_texto(texto: str) -> str:
    lineas = texto.split("\n")
    salida: list[str] = []
    i = 0
    while i < len(lineas):
        linea = lineas[i]
        m = _TABLA_INICIO_RE.match(linea)
        if not m:
            salida.append(linea)
            i += 1
            continue

        salida.append(linea)
        indent_tabla = len(m.group("indent"))
        i += 1
        bloque: list[str] = []
        while i < len(lineas):
            actual = lineas[i]
            if actual.strip() == "":
                break
            if _indentacion(actual) <= indent_tabla:
                break
            bloque.append(actual)
            i += 1

        if bloque:
            indent_bloque = " " * _indentacion(bloque[0])
            salida.extend(_realinear_bloque(bloque, indent_bloque))

    return "\n".join(salida)


def main(argv: list[str] | None = None, repo_root: Path = REPO_ROOT) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if len(args) != 1:
        print("Uso: make bus-formatear TENANT=<slug>")
        return 2
    try:
        directorio = dataset_dir(args[0], repo_root)
    except TenantDesconocido as exc:
        print(f"✗ {exc}")
        return 2
    for path in sorted((directorio / "lineas").glob("*.yaml")):
        original = path.read_text(encoding="utf-8")
        formateado = formatear_texto(original)
        if formateado != original:
            path.write_text(formateado, encoding="utf-8")
            print(f"Realineado: {path}")
        else:
            print(f"Sin cambios: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
