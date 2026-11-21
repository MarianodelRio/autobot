"""Tablas de horarios (`horarios:` de un fichero de línea): análisis del texto."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from packs.bus.formato.comun import PENDIENTE_RE

# Celda de hora: `HH:MM`, o `HH:MM>HH:MM` (llegada>salida en la misma parada,
# solo en paradas intermedias), seguida de letras de observación de parada.
_HH_MM = r"(?:[01]\d|2[0-3]):[0-5]\d"
CELDA_HORA_RE = re.compile(rf"^({_HH_MM})(?:>({_HH_MM}))?([A-Z]*)$")
BUS_ID_RE = re.compile(r"^[a-z0-9-]+$")


@dataclass
class FilaTabla:
    valores: list[str]
    obs_viaje: list[str]
    pendientes: list[str]
    numero: int  # fila dentro de la tabla (1-based, sin cabecera ni comentarios)
    # ids escritos como `bus:<id>` tras el `|` (sin validar; puede haber 0, 1 o más)
    bus: list[str] = field(default_factory=list)


def parse_tabla(texto: str) -> tuple[list[str] | None, list[FilaTabla]]:
    """Devuelve (cabecera, filas). cabecera es None si no hay ninguna línea útil."""
    lineas = [
        line for line in texto.splitlines() if line.strip() and not line.strip().startswith("#")
    ]
    if not lineas:
        return None, []
    cabecera = lineas[0].split()
    filas: list[FilaTabla] = []
    for i, linea in enumerate(lineas[1:], start=1):
        if "|" in linea:
            izquierda, derecha = linea.split("|", 1)
            valores = izquierda.split()
            resto = derecha.split()
        else:
            valores = linea.split()
            resto = []
        buses = [tok[len("bus:") :] for tok in resto if tok.startswith("bus:")]
        resto = [tok for tok in resto if not tok.startswith("bus:")]
        obs_viaje = [tok for tok in resto if not PENDIENTE_RE.match(tok)]
        pendientes = [tok for tok in resto if PENDIENTE_RE.match(tok)]
        filas.append(
            FilaTabla(
                valores=valores,
                obs_viaje=obs_viaje,
                pendientes=pendientes,
                numero=i,
                bus=buses,
            )
        )
    return cabecera, filas
