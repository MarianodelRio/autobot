"""Lectura de ficheros YAML y comprobación de claves, comunes a todos los validadores."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def cargar_yaml(path: Path, errores: list[str]) -> dict[str, Any] | None:
    try:
        texto = path.read_text(encoding="utf-8")
    except OSError as exc:
        errores.append(f"{path}: no se puede leer el fichero ({exc})")
        return None
    try:
        datos = yaml.safe_load(texto)
    except yaml.YAMLError as exc:
        errores.append(f"{path}: YAML mal formado ({exc})")
        return None
    if datos is None:
        datos = {}
    if not isinstance(datos, dict):
        errores.append(f"{path}: YAML mal formado (se esperaba un mapa en la raíz)")
        return None
    return datos


def claves_desconocidas(
    campos: dict[str, Any],
    permitidos: set[str],
    etiqueta: str,
    path: Path,
    errores: list[str],
    *,
    ignorar: tuple[str, ...] | set[str] = (),
) -> None:
    """Un error por cada clave de `campos` que no está en `permitidos`."""
    desconocidas = [k for k in campos if k not in permitidos and k not in ignorar]
    for k in sorted(desconocidas, key=str):
        msg = f"{path}: {etiqueta}: campo desconocido '{k}'"
        if campos[k] is None and "nombre" in campos:
            msg += " (¿un nombre con coma sin comillas?)"
        errores.append(msg)
