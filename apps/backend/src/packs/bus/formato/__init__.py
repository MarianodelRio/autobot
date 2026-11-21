"""packs/bus/formato — parser y validador único de `horarios/`.

Paquete con un módulo por fichero del dataset (`localidades`, `calendario`,
`observaciones`, `linea`/`tabla`, `buses`) y `dataset.validar`, que los junta.
Este `__init__` reexporta la API que usa el resto del pack, las herramientas y
los tests; lo demás es interno de cada módulo.
"""

from packs.bus.formato.dataset import validar
from packs.bus.formato.normalizar import normalizar
from packs.bus.formato.observaciones import texto_observacion
from packs.bus.formato.tabla import parse_tabla
from packs.bus.formato.temporadas import (
    DIAS_INDIVIDUALES,
    GRUPOS_DIA,
    NOMBRES_PUBLICOS_TEMPORADA,
    temporada_de_linea,
)
from packs.bus.modelo import Modelo, Resultado

__all__ = [
    "DIAS_INDIVIDUALES",
    "GRUPOS_DIA",
    "NOMBRES_PUBLICOS_TEMPORADA",
    "Modelo",
    "Resultado",
    "normalizar",
    "parse_tabla",
    "temporada_de_linea",
    "texto_observacion",
    "validar",
]
