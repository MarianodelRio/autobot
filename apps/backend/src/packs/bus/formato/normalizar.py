"""Normalización única de nombres de localidad y parada."""

from __future__ import annotations

from core.text import normalize

# Artículos y preposiciones de enlace que se descartan al
# normalizar (villagrande soto = Villagrande del Soto).
_PALABRAS_VACIAS_NORMALIZAR = frozenset({"el", "la", "los", "las", "de", "del"})


def normalizar(texto: str) -> str:
    """Normalización única de nombres de localidad/parada y sus alias:
    `core.text.normalize` (minúsculas, sin tildes,
    sin puntuación, colapsada a espacio) y sin artículos/preposiciones de
    enlace. La comparten el validador y `packs.bus.matcher`; ningún
    otro módulo vuelve a normalizar un nombre por su cuenta."""
    return " ".join(p for p in normalize(texto).split() if p not in _PALABRAS_VACIAS_NORMALIZAR)
