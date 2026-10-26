"""packs/bus/matcher.py — coincidencia de texto libre con localidades.

Índice puro y sin estado sobre un `Horarios` ya cargado (`loader.cargar`):
nada de WhatsApp ni de textos en español (eso vive en fase 4, en
`conversation.py` y `messages.py`). La normalización de nombres es una única
función compartida con el validador: `packs.bus.formato.normalizar`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from packs.bus import formato
from packs.bus.modelo import Linea, Localidad

if TYPE_CHECKING:
    from packs.bus.loader import Horarios

MIN_LETRAS = 3
MAX_CANDIDATAS = 9
LETRAS_ERRATA_CORTA = 5

# Relleno inicial que se quita del texto del cliente ya
# normalizado ("desde pozoblanco", "¿desde pozoblanco?", "voy a cordoba").
# Se hace después de normalizar para que la puntuación ("¿", ",") no lo
# impida. Comprobado una sola vez, de más largo a más corto, para que "voy a"
# se quite entero y no deje una "a" suelta.
_RELLENO_INICIAL = ("hacia", "desde", "voy a", "para", "a")


@dataclass(frozen=True)
class Coincidencia:
    tipo: str  # unico | confirmar | elegir | demasiadas | sin_coincidencia
    localidades: tuple[str, ...]  # ids, orden alfabético por nombre normalizado
    texto_normalizado: str


def damerau(a: str, b: str) -> int:
    """Distancia de Damerau-Levenshtein (con trasposición de adyacentes),
    sin dependencias nuevas."""
    la, lb = len(a), len(b)
    d = [[0] * (lb + 1) for _ in range(la + 1)]
    for i in range(la + 1):
        d[i][0] = i
    for j in range(lb + 1):
        d[0][j] = j
    for i in range(1, la + 1):
        for j in range(1, lb + 1):
            costo = 0 if a[i - 1] == b[j - 1] else 1
            d[i][j] = min(
                d[i - 1][j] + 1,  # borrado
                d[i][j - 1] + 1,  # inserción
                d[i - 1][j - 1] + costo,  # sustitución
            )
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                d[i][j] = min(d[i][j], d[i - 2][j - 2] + 1)  # trasposición
    return d[la][lb]


def _quitar_relleno_inicial(normalizado: str) -> str:
    for palabra in _RELLENO_INICIAL:
        if normalizado.startswith(palabra + " "):
            return normalizado[len(palabra) + 1 :]
    return normalizado


class Matcher:
    """Índice construido una vez sobre un `Horarios` ya cargado."""

    def __init__(self, horarios: Horarios) -> None:
        self.completas: dict[str, set[str]] = {}
        self.solo_exactas: dict[str, str] = {}
        self._localidades = horarios.modelo.localidades

        for lid, loc in horarios.modelo.localidades.items():
            claves = {formato.normalizar(loc.nombre)}
            claves |= {formato.normalizar(a) for a in loc.alias}
            for clave in claves:
                if clave == "":
                    continue
                self.completas.setdefault(clave, set()).add(lid)

        for parada in horarios.modelo.paradas.values():
            clave = formato.normalizar(parada.nombre)
            if clave == "":
                continue
            self.solo_exactas[clave] = parada.localidad

    def buscar(self, texto: str) -> Coincidencia:
        q = _quitar_relleno_inicial(formato.normalizar(texto))

        if q == "":
            return Coincidencia(tipo="sin_coincidencia", localidades=(), texto_normalizado=q)

        candidatas: set[str] = set()
        via_errata = False

        if q in self.completas:
            candidatas = set(self.completas[q])
        elif q in self.solo_exactas:
            candidatas = {self.solo_exactas[q]}
        elif len(q) >= MIN_LETRAS:
            for clave, ids in self.completas.items():
                if clave.startswith(q):
                    candidatas |= ids
            if not candidatas:
                for clave, ids in self.completas.items():
                    umbral = 1 if len(clave) <= LETRAS_ERRATA_CORTA else 2
                    if damerau(q, clave) <= umbral:
                        candidatas |= ids
                if candidatas:
                    via_errata = True

        n = len(candidatas)
        if n == 0:
            tipo = "sin_coincidencia"
        elif n == 1:
            tipo = "confirmar" if via_errata else "unico"
        elif n <= MAX_CANDIDATAS:
            tipo = "elegir"
        else:
            tipo = "demasiadas"

        ordenadas = tuple(sorted(candidatas, key=lambda lid: self._nombre_normalizado(lid)))
        return Coincidencia(tipo=tipo, localidades=ordenadas, texto_normalizado=q)

    def _nombre_normalizado(self, lid: str) -> str:
        # Solo se llama con ids ya presentes en el índice, siempre localidades
        # reales del modelo cargado.
        return formato.normalizar(self._localidades[lid].nombre)


def lineas(
    horarios: Horarios,
) -> tuple[tuple[Linea, tuple[Localidad, ...]], ...]:
    """Líneas en orden alfabético por título (`Linea.titulo`, normalizado),
    cada una con sus pueblos en orden alfabético.
    Descarta las líneas sin pueblos y las aldeas pendientes (ya excluidas en
    `Horarios.lineas_pueblos`)."""
    resultado: list[tuple[Linea, tuple[Localidad, ...]]] = []
    for lid, ids in horarios.lineas_pueblos.items():
        if not ids:
            continue
        resultado.append(
            (
                horarios.modelo.lineas[lid],
                tuple(horarios.modelo.localidades[i] for i in ids),
            )
        )
    return tuple(resultado)
