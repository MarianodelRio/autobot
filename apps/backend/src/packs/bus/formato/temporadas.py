"""Días de la semana, estados de día y temporadas de línea.

Lo que comparten el validador y el motor de consulta: las claves de día, sus
grupos, el nombre público de cada temporada y la resolución de la temporada de
una línea para un día del año (sin año: los rangos se repiten cada año).
"""

from __future__ import annotations

import calendar
import re
from functools import lru_cache

from core.dates import WEEKDAY_KEYS
from packs.bus.modelo import Linea, Temporada

DIAS_INDIVIDUALES = (*WEEKDAY_KEYS, "festivos")

GRUPOS_DIA: dict[str, frozenset[str]] = {
    "lunes": frozenset({"lunes"}),
    "martes": frozenset({"martes"}),
    "miercoles": frozenset({"miercoles"}),
    "jueves": frozenset({"jueves"}),
    "viernes": frozenset({"viernes"}),
    "sabado": frozenset({"sabado"}),
    "domingo": frozenset({"domingo"}),
    "festivos": frozenset({"festivos"}),
    "lunes-viernes": frozenset({"lunes", "martes", "miercoles", "jueves", "viernes"}),
    "lunes-jueves": frozenset({"lunes", "martes", "miercoles", "jueves"}),
    "martes-viernes": frozenset({"martes", "miercoles", "jueves", "viernes"}),
    "sabados-domingos": frozenset({"sabado", "domingo"}),
    "domingos-festivos": frozenset({"domingo", "festivos"}),
    "sabados-domingos-festivos": frozenset({"sabado", "domingo", "festivos"}),
}

ESTADOS_DIA = {"horario", "sin_servicio", "sin_datos"}

# Temporadas con nombre público: solo estas se muestran al cliente como
# "horario de X" en la cabecera del resultado. Una temporada
# nueva con nombre propio exige ampliar esta tabla.
NOMBRES_PUBLICOS_TEMPORADA = {
    "invierno": "invierno",
    "verano": "verano",
    "agosto": "agosto",
}

# Los 366 días del año (mes, día), usando un año bisiesto como calendario de
# referencia. Sirve para comprobar que las temporadas cubren el año entero,
# incluido el 29 de febrero, sin años reales.
DIAS_DEL_ANIO: list[tuple[int, int]] = [
    (mes, dia) for mes in range(1, 13) for dia in range(1, calendar.monthrange(2024, mes)[1] + 1)
]
INDICE_DIA = {md: i for i, md in enumerate(DIAS_DEL_ANIO)}

_RANGO_TEMPORADA_RE = re.compile(r"^(\d{2})/(\d{2})\s*-\s*(\d{2})/(\d{2})$")


def parse_temporada_rango(rango: str) -> list[int] | None:
    """Devuelve la lista de índices (en `DIAS_DEL_ANIO`) que cubre el rango, o
    None si el formato es inválido."""
    rango = rango.strip()
    if rango.lower() == "todo el año" or rango.lower() == "todo el ano":
        return list(range(len(DIAS_DEL_ANIO)))
    m = _RANGO_TEMPORADA_RE.match(rango)
    if not m:
        return None
    d1, m1, d2, m2 = (int(x) for x in m.groups())
    try:
        i1 = INDICE_DIA[(m1, d1)]
        i2 = INDICE_DIA[(m2, d2)]
    except KeyError:
        return None
    if i1 <= i2:
        return list(range(i1, i2 + 1))
    return list(range(i1, len(DIAS_DEL_ANIO))) + list(range(0, i2 + 1))


@lru_cache(maxsize=512)
def _temporada_por_dia(temporadas: tuple[Temporada, ...]) -> dict[tuple[int, int], Temporada]:
    """(mes, día) -> temporada que lo cubre; si hubiera solape gana la primera
    declarada. Se calcula una vez por juego de temporadas, no por consulta."""
    por_dia: dict[tuple[int, int], Temporada] = {}
    for temporada in temporadas:
        indices = parse_temporada_rango(temporada.rango)
        if indices is None:
            continue
        for i in indices:
            por_dia.setdefault(DIAS_DEL_ANIO[i], temporada)
    return por_dia


def temporada_de_linea(linea: Linea, mes: int, dia: int) -> Temporada | None:
    """Temporada de `linea` vigente para ese día/mes.

    Único punto que vuelve a interpretar un rango de temporada de línea fuera
    de la validación: usa `parse_temporada_rango`, el mismo parser
    año-independiente que la validación de la línea.
    `packs.bus.calendario.temporada_de` delega aquí; nadie más vuelve a
    parsear esto."""
    return _temporada_por_dia(linea.temporadas).get((mes, dia))
