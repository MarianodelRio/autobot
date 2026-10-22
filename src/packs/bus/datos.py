"""packs/bus/datos.py — datos de horarios de un tenant, ya cargados en memoria
(buscaBus/design.md, fase 4; design.md §10.1).

En buscaBus este módulo guardaba un `Datos` global protegido por un candado
(`instalar()`/`actual()`). En FlowPilot los datos son por tenant: el registro
de tenants guarda lo que devuelve `load_data` y el pack lo recibe en
`ctx.data`, así que aquí solo queda la carga.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from packs.bus import loader
from packs.bus.formato import normalizar
from packs.bus.loader import Horarios


@dataclass(frozen=True)
class Datos:
    horarios: Horarios
    menu_origen: tuple[str, ...]


def cargar(directorio: Path | str, pueblos_menu: list[str]) -> Datos:
    """Carga `horarios/` y resuelve `pueblos_menu` contra las localidades
    reales. Lanza `RuntimeError` con el nombre del pueblo si no se encuentra
    (exacto, sin prefijo ni errata), está duplicado, o no tiene ningún viaje
    en `horarios.localidad_viajes`."""
    horarios = loader.cargar(directorio)
    modelo = horarios.modelo

    # id de localidad por nombre normalizado, para una búsqueda exacta.
    por_nombre: dict[str, str] = {
        normalizar(loc.nombre): lid for lid, loc in modelo.localidades.items()
    }

    menu_ids: list[str] = []
    vistos: set[str] = set()
    for pueblo in pueblos_menu:
        clave = normalizar(pueblo)
        lid = por_nombre.get(clave)
        if lid is None:
            raise RuntimeError(
                f"[DATOS] start_menu_towns: '{pueblo}' no es una localidad conocida de horarios/"
            )
        if lid in vistos:
            raise RuntimeError(f"[DATOS] start_menu_towns: '{pueblo}' está duplicado")
        if not horarios.localidad_viajes.get(lid):
            raise RuntimeError(
                f"[DATOS] start_menu_towns: '{pueblo}' no tiene ningún viaje en horarios/"
            )
        vistos.add(lid)
        menu_ids.append(lid)

    return Datos(horarios=horarios, menu_origen=tuple(menu_ids))
