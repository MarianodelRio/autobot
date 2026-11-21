"""packs/bus/fechas.py — lector de fechas en formato cerrado día/mes[/año].

Sin lenguaje natural ("mañana", "el viernes que viene"): solo día y mes en
números, con año opcional. Puro: `hoy` lo pasa el llamador; no importa `zoneinfo` ni `pytz` aquí.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

DIAS_FECHA_PASADA = 30

# Separador `/`, `-` o `.` (con espacios alrededor si se quiere), el mismo en toda la fecha;
# o solo espacios (`25 12`). Con espacios, el mes debe ser un mes (`10 30` es una hora,
# no una fecha).
_FECHA_RE = re.compile(
    r"^(\d{1,2})\s*(?P<sep>[/\-.])\s*(\d{1,2})(?:\s*(?P=sep)\s*(\d{2}|\d{4}))?$"
    r"|^(\d{1,2}) +(\d{1,2})(?: +(\d{2}|\d{4}))?$"
)


@dataclass(frozen=True)
class LecturaFecha:
    # ok | formato | inexistente | pasada | confirmar (la fecha cae en otro año: hay que
    # preguntar, nunca se adivina en silencio)
    estado: str
    fecha: date | None = None  # cuando estado es "ok" o "confirmar"


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


def _necesita_confirmar(dia: int, mes: int, hoy: date, proxima: date) -> bool:
    """Una fecha sin año que no cae en el año actual solo se da por buena sin preguntar si
    es el año siguiente y queda más cerca por delante que por detrás (`5/1` en diciembre);
    el 29/02 que salta a otro año siempre se pregunta."""
    if proxima.year == hoy.year:
        return False
    if (dia, mes) == (29, 2) or proxima.year != hoy.year + 1:
        return True
    ultima = _ultima_ocurrencia(dia, mes, hoy)
    return (proxima - hoy).days > (hoy - ultima).days


def leer_fecha(texto: str, hoy: date) -> LecturaFecha:
    m = _FECHA_RE.match(texto.strip())
    if not m:
        return LecturaFecha(estado="formato")

    if m.group(1) is not None:
        dia_txt, mes_txt, anio_txt = m.group(1), m.group(3), m.group(4)
    else:
        dia_txt, mes_txt, anio_txt = m.group(5), m.group(6), m.group(7)
        if not 1 <= int(mes_txt) <= 12:
            return LecturaFecha(estado="formato")  # `10 30`: una hora, no una fecha
    dia, mes = int(dia_txt), int(mes_txt)

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
    if _necesita_confirmar(dia, mes, hoy, proxima):
        return LecturaFecha(estado="confirmar", fecha=proxima)
    return LecturaFecha(estado="ok", fecha=proxima)
