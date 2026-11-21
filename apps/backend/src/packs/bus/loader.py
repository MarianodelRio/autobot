"""packs/bus/loader.py — carga `horarios/` a memoria al arrancar
el bot, usando el único parser/validador (`formato.py`).

Nunca devuelve datos parciales o ambiguos: si `horarios/` no valida, lanza
`HorariosInvalidos` con la lista completa de errores en vez de devolver un
`Horarios` a medio construir.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from functools import cached_property
from pathlib import Path
from typing import Any

from packs.bus import formato
from packs.bus.modelo import Linea, Localidad, Modelo, Viaje


class HorariosInvalidos(Exception):
    """`horarios/` no valida. Lleva la lista completa de errores de
    `formato.validar()`."""

    def __init__(self, errores: list[str]) -> None:
        self.errores = errores
        mensaje = "\n".join(f"  - {e}" for e in errores)
        super().__init__(f"horarios/ no valida ({len(errores)} error(es)):\n{mensaje}")


@dataclass(frozen=True)
class Horarios:
    """`Modelo` ya validado, más índices de solo lectura precalculados para
    que el motor de consulta (`query.py`) no tenga que recorrer todas las
    líneas en cada consulta."""

    modelo: Modelo
    # localidad -> códigos de parada de esa localidad, en cualquier línea
    localidad_paradas: dict[str, tuple[str, ...]]
    # localidad -> viajes que paran en alguna parada de esa localidad
    localidad_viajes: dict[str, tuple[Viaje, ...]]
    # Todos los viajes, en el orden de `modelo.lineas` y, dentro de cada línea, de
    # `linea.viajes`; `localidad_viajes_idx` son las posiciones (ascendentes) de
    # `localidad_viajes` en esta tupla, un id entero estable para intersecar.
    viajes: tuple[Viaje, ...] = ()
    localidad_viajes_idx: dict[str, tuple[int, ...]] = field(default_factory=dict)
    # línea -> fecha -> (nombre del festivo, id de localidad): los festivos
    # locales que aplica cada línea. Una línea aplica los de una
    # localidad si alguno de sus viajes tiene una parada en ella.
    festivos_por_linea: dict[str, dict[date, tuple[str, str]]] = field(default_factory=dict)
    # línea -> ids de las localidades por las que pasa (excluidas las aldeas
    # pendientes), en orden alfabético por nombre normalizado. El propio dict
    # está ordenado por título de línea normalizado.
    lineas_pueblos: dict[str, tuple[str, ...]] = field(default_factory=dict)
    # (origen, destino) -> lo que solo depende del par; lo rellena `query`.
    cache_pares: dict[tuple[str, str], Any] = field(
        default_factory=dict, init=False, repr=False, compare=False
    )

    @cached_property
    def lineas_con_pueblos(
        self,
    ) -> tuple[tuple[Linea, tuple[Localidad, ...]], ...]:
        """Líneas en el orden de `lineas_pueblos` (alfabético por título), cada
        una con sus pueblos ya resueltos a `Localidad`. Descarta las líneas sin
        pueblos. Se calcula una vez por carga, no por turno de conversación."""
        return tuple(
            (self.modelo.lineas[lid], tuple(self.modelo.localidades[i] for i in ids))
            for lid, ids in self.lineas_pueblos.items()
            if ids
        )


def calcular_lineas_pueblos(modelo: Modelo) -> dict[str, tuple[str, ...]]:
    """línea -> localidades por las que pasa. Único sitio que lo decide;
    lo usan `cargar()` y la vista de revisión. Excluye las localidades
    pendientes (aldeas sin hora de paso propia). Pueblos por nombre
    normalizado (desempate por id); líneas por título normalizado (desempate
    por id); el dict devuelto ya está en ese orden."""
    por_linea: dict[str, list[str]] = {}
    for lid, linea in modelo.lineas.items():
        ids = {
            modelo.paradas[paso.parada].localidad
            for viaje in linea.viajes
            for paso in viaje.pasos
            if paso.parada in modelo.paradas
        }
        ids = {
            i for i in ids if i in modelo.localidades and modelo.localidades[i].pendiente is None
        }
        por_linea[lid] = sorted(
            ids, key=lambda i: (formato.normalizar(modelo.localidades[i].nombre), i)
        )
    orden = sorted(
        modelo.lineas,
        key=lambda lid: (formato.normalizar(modelo.lineas[lid].titulo), lid),
    )
    return {lid: tuple(por_linea[lid]) for lid in orden}


def calcular_festivos_por_linea(
    modelo: Modelo,
) -> dict[str, dict[date, tuple[str, str]]]:
    """línea -> fecha -> (nombre, id de localidad) de los festivos locales que
    aplica cada línea: una línea aplica los de una localidad si alguno
    de sus viajes tiene una parada en ella. Único sitio que lo decide; lo usan
    `cargar()` y la vista de revisión."""
    resultado: dict[str, dict[date, tuple[str, str]]] = {}
    calendario = modelo.calendario
    if calendario is None or not calendario.festivos_locales:
        return resultado
    for lid, linea in modelo.lineas.items():
        localidades_linea = {
            modelo.paradas[paso.parada].localidad
            for viaje in linea.viajes
            for paso in viaje.pasos
            if paso.parada in modelo.paradas
        }
        de_la_linea: dict[date, tuple[str, str]] = {}
        for localidad_id in sorted(calendario.festivos_locales):
            if localidad_id not in localidades_linea:
                continue
            for fecha, nombre in calendario.festivos_locales[localidad_id].items():
                de_la_linea.setdefault(fecha, (nombre, localidad_id))
        if de_la_linea:
            resultado[lid] = de_la_linea
    return resultado


def cargar(directorio: Path | str) -> Horarios:
    """Valida `horarios/` y construye `Horarios`. Lanza `HorariosInvalidos`
    si hay algún error; nunca devuelve un resultado parcial."""
    resultado = formato.validar(directorio)
    if resultado.errores:
        raise HorariosInvalidos(resultado.errores)

    modelo = resultado.modelo
    assert modelo is not None

    localidad_paradas: dict[str, set[str]] = {}
    todos: list[Viaje] = []
    localidad_idx: dict[str, list[int]] = {}

    for codigo, parada in modelo.paradas.items():
        localidad_paradas.setdefault(parada.localidad, set()).add(codigo)

    for linea in modelo.lineas.values():
        for viaje in linea.viajes:
            indice = len(todos)
            todos.append(viaje)
            localidades_del_viaje = {
                modelo.paradas[paso.parada].localidad
                for paso in viaje.pasos
                if paso.parada in modelo.paradas
            }
            for localidad_id in localidades_del_viaje:
                localidad_idx.setdefault(localidad_id, []).append(indice)

    return Horarios(
        modelo=modelo,
        localidad_paradas={
            lid: tuple(sorted(codigos)) for lid, codigos in localidad_paradas.items()
        },
        localidad_viajes={
            lid: tuple(todos[i] for i in indices) for lid, indices in localidad_idx.items()
        },
        viajes=tuple(todos),
        localidad_viajes_idx={lid: tuple(indices) for lid, indices in localidad_idx.items()},
        festivos_por_linea=calcular_festivos_por_linea(modelo),
        lineas_pueblos=calcular_lineas_pueblos(modelo),
    )
