"""packs/bus/fechas.py — lector de fechas en formato cerrado día/mes[/año].

Sin lenguaje natural ("mañana", "el viernes que viene"): solo día y mes en
números, con año opcional. Puro: `hoy` lo pasa el llamador (fase 4 pasará
`calendario.hoy()`); no importa `zoneinfo` ni `pytz` aquí.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

DIAS_FECHA_PASADA = 30

_FECHA_RE = re.compile(r"^(\d{1,2})\s*[/\-. ]\s*(\d{1,2})(?:\s*[/\-. ]\s*(\d{2}|\d{4}))?$")


@dataclass(frozen=True)
class LecturaFecha:
    estado: str  # ok | formato | inexistente | pasada
    fecha: date | None = None  # solo cuando estado == "ok"


def _es_fecha_valida(dia: int, mes: int, anio: int) -> bool:
    try:
        date(anio, mes, dia)
        return True
    except ValueError:
        return False


def _ultima_ocurrencia(dia: int, mes: int, hoy: date) -> date:
    """Última vez (año por año, hacia atrás) que cayó ese día/mes, antes de
    `hoy` (estrictamente). Necesario para el 29 de febrero."""
    anio = hoy.year
    while True:
        if _es_fecha_valida(dia, mes, anio):
            candidata = date(anio, mes, dia)
            if candidata < hoy:
                return candidata
        anio -= 1


def _proxima_ocurrencia(dia: int, mes: int, hoy: date) -> date:
    """Próxima vez (año por año, hacia adelante) que cae ese día/mes, desde
    `hoy` incluido."""
    anio = hoy.year
    while True:
        if _es_fecha_valida(dia, mes, anio):
            candidata = date(anio, mes, dia)
            if candidata >= hoy:
                return candidata
        anio += 1


def _dia_mes_valido_en_algun_anio(dia: int, mes: int) -> bool:
    if mes < 1 or mes > 12:
        return False
    # 29/02 es válido en años bisiestos; probamos un año bisiesto conocido.
    return _es_fecha_valida(dia, mes, 2024)


def leer_fecha(texto: str, hoy: date) -> LecturaFecha:
    m = _FECHA_RE.match(texto.strip())
    if not m:
        return LecturaFecha(estado="formato")

    dia = int(m.group(1))
    mes = int(m.group(2))
    anio_txt = m.group(3)

    if anio_txt is not None:
        anio = int(anio_txt)
        if len(anio_txt) == 2:
            anio += 2000
        if not _es_fecha_valida(dia, mes, anio):
            return LecturaFecha(estado="inexistente")
        fecha = date(anio, mes, dia)
        if fecha < hoy:
            return LecturaFecha(estado="pasada")
        return LecturaFecha(estado="ok", fecha=fecha)

    if not _dia_mes_valido_en_algun_anio(dia, mes):
        return LecturaFecha(estado="inexistente")

    ultima = _ultima_ocurrencia(dia, mes, hoy)
    proxima = _proxima_ocurrencia(dia, mes, hoy)
    if (hoy - ultima).days <= DIAS_FECHA_PASADA:
        return LecturaFecha(estado="pasada")
    return LecturaFecha(estado="ok", fecha=proxima)
