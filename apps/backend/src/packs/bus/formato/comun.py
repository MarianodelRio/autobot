"""Patrones y comprobaciones comunes a los validadores de `horarios/`."""

from __future__ import annotations

import re
from pathlib import Path

from core.limits import MAX_ID_BYTES

PENDIENTE_RE = re.compile(r"^P\d{2}$")

# packs/bus/interactive.py construye los ids de botón/fila con estos prefijos
# ("loc:<id de localidad>", "linea:<id de línea>:<página>"); el límite común de
# canal (MAX_ID_BYTES) se comprueba aquí, no al usarse, para rechazar el
# dataset con un mensaje claro en vez de que la conversación falle.
PREFIJO_LOC = "loc:"
PREFIJO_LINEA = "linea:"
SUFIJO_LINEA_MARGEN = ":999"  # página con hasta 3 cifras, de sobra


def validar_id_de_canal(
    errores: list[str], path: Path, que: str, valor: str, overhead: int
) -> None:
    size = len(valor.encode()) + overhead
    if size > MAX_ID_BYTES:
        errores.append(
            f"{path}: {que} '{valor}' sería un id de {size} bytes al mostrarse en una "
            f"fila o botón (máximo {MAX_ID_BYTES})"
        )
