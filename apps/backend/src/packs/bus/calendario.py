"""packs/bus/calendario.py — lógica pura de calendario: temporada de una línea,
tipo de día y periodo lectivo para una fecha dada.

No hace E/S ni lee el reloj: recibe el objeto `Calendario` ya validado por
`formato/` y la fecha a resolver.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from core.dates import WEEKDAY_KEYS
from packs.bus import formato
from packs.bus.modelo import Calendario, Linea, Temporada


class FueraDeCalendario(Exception):
    """La fecha consultada está fuera de la vigencia de `calendario.yaml`."""


@dataclass(frozen=True)
class InfoDia:
    fecha: date
    dia_semana: str  # lunes..domingo (día real de la semana, aunque sea festivo)
    clase_dia: str  # una de formato.DIAS_INDIVIDUALES: el día de la semana, o
    # "festivos" si es festivo (decisión 1: el festivo siempre gana)
    es_festivo: bool
    nombre_festivo: str | None
    es_lectivo: bool
    mes: int


def _en_algun_rango(fecha: date, rangos: tuple[tuple[date, date], ...]) -> bool:
    return any(inicio <= fecha <= fin for inicio, fin in rangos)


def info_dia(
    calendario: Calendario, fecha: date, permitir_fuera_de_vigencia: bool = False
) -> InfoDia:
    """Resuelve el tipo de día de `fecha` según `calendario`. Lanza
    `FueraDeCalendario` si `fecha` cae fuera de la vigencia del calendario, salvo con
    `permitir_fuera_de_vigencia=True` (solo para los días sin servicio en ninguna
    línea, que se conocen sin calendario vigente; el nombre del festivo será None si
    no está cargado)."""
    fuera = fecha < calendario.vigencia_inicio or fecha > calendario.vigencia_fin
    if fuera and not permitir_fuera_de_vigencia:
        raise FueraDeCalendario(
            f"{fecha.strftime('%d/%m/%Y')} está fuera de la vigencia del "
            f"calendario ({calendario.vigencia_inicio.strftime('%d/%m/%Y')} - "
            f"{calendario.vigencia_fin.strftime('%d/%m/%Y')})"
        )

    dia_semana = WEEKDAY_KEYS[fecha.weekday()]
    nombre_festivo = calendario.festivos.get(fecha)
    es_festivo = nombre_festivo is not None

    # Decisión 1: un festivo siempre gana, sea cual sea el día de la semana
    # Un festivo en sábado usa la clase "festivos", no "sabado".
    clase_dia = "festivos" if es_festivo else dia_semana

    es_lectivo = (
        calendario.inicio_clases <= fecha <= calendario.fin_clases
        and fecha.weekday() < 5  # lunes..viernes
        and not es_festivo
        and not _en_algun_rango(fecha, calendario.vacaciones)
        and fecha not in calendario.no_lectivos
    )

    return InfoDia(
        fecha=fecha,
        dia_semana=dia_semana,
        clase_dia=clase_dia,
        es_festivo=es_festivo,
        nombre_festivo=nombre_festivo,
        es_lectivo=es_lectivo,
        mes=fecha.month,
    )


def clase_dia_linea(
    info: InfoDia, festivos_locales_de_la_linea: dict[date, tuple[str, str]]
) -> tuple[str, tuple[str, str] | None]:
    """Clase de día que aplica una línea concreta en `info.fecha` :
    "festivos" si el día es festivo general o festivo local de alguna
    localidad que la línea toca; si no, la clase del día de la semana.
    Devuelve también el festivo local `(nombre, id de localidad)` que tenga la
    línea ese día (aunque además sea festivo general), o None. `InfoDia` y
    `es_lectivo` no cambian por un festivo local ."""
    festivo_local = festivos_locales_de_la_linea.get(info.fecha)
    if info.es_festivo or festivo_local is not None:
        return "festivos", festivo_local
    return info.clase_dia, None


def temporada_de(linea: Linea, fecha: date) -> Temporada | None:
    """Temporada de `linea` vigente en `fecha`. Delega en
    `formato.temporada_de_linea`: el único sitio que interpreta un rango de
    temporada de línea es `formato/temporadas.py`."""
    return formato.temporada_de_linea(linea, fecha.month, fecha.day)
