"""Helpers de tipos de los tests del pack `bus`: `formato.validar` devuelve un
`Modelo` opcional, y los tests que lo leen solo tienen sentido si validó."""

from __future__ import annotations

from packs.bus.formato import Modelo, Resultado
from packs.bus.modelo import Calendario


def modelo_de(resultado: Resultado) -> Modelo:
    assert resultado.modelo is not None, resultado.errores
    return resultado.modelo


def calendario_de(resultado: Resultado) -> Calendario:
    calendario = modelo_de(resultado).calendario
    assert calendario is not None
    return calendario
