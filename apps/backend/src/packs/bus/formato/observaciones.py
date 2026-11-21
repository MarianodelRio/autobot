"""Observaciones (`observaciones.yaml`): validación y texto que ve el cliente."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from packs.bus.formato.yaml_io import claves_desconocidas
from packs.bus.modelo import Linea, Observacion

CONDICIONES_CONOCIDAS = {
    "a_demanda",
    "solo_viernes_lectivo",
    "solo_si_viajeros",
}
CAMPOS_OBSERVACION = {"letra", "tipo", "ambitos", "texto"}
MARCADOR_RE = re.compile(r"\{([^}]*)\}")


def validar_observaciones(
    datos: dict[str, Any], path: Path, errores: list[str]
) -> dict[str, Observacion]:
    observaciones: dict[str, Observacion] = {}
    for oid, campos in datos.items():
        if isinstance(campos, dict):
            claves_desconocidas(campos, CAMPOS_OBSERVACION, f"observación '{oid}'", path, errores)
        if (
            not isinstance(campos, dict)
            or "tipo" not in campos
            or "ambitos" not in campos
            or "texto" not in campos
        ):
            errores.append(f"{path}: observación '{oid}' sin 'tipo', 'ambitos' o 'texto'")
            continue
        tipo = campos["tipo"]
        if tipo not in ("condicion", "aviso"):
            errores.append(f"{path}: observación '{oid}' con tipo desconocido '{tipo}'")
            continue
        ambitos = campos["ambitos"]
        if (
            not isinstance(ambitos, list)
            or not ambitos
            or any(a not in ("parada", "viaje", "linea") for a in ambitos)
        ):
            errores.append(f"{path}: observación '{oid}' con ámbitos inválidos {ambitos!r}")
            continue
        letra = campos.get("letra")
        if "parada" in ambitos and letra is None:
            errores.append(
                f"{path}: observación '{oid}' tiene ámbito 'parada' pero no define 'letra'"
            )
        if tipo == "condicion" and oid not in CONDICIONES_CONOCIDAS:
            errores.append(
                f"{path}: observación '{oid}' es una condición que el motor no "
                f"sabe aplicar (conocidas: {sorted(CONDICIONES_CONOCIDAS)})"
            )
        texto = str(campos["texto"])
        for m in MARCADOR_RE.finditer(texto):
            marcador = m.group(1)
            if marcador != "telefono":
                errores.append(
                    f"{path}: observación '{oid}' tiene un marcador desconocido "
                    f"'{{{marcador}}}' en 'texto' (solo se admite '{{telefono}}')"
                )
        observaciones[oid] = Observacion(
            id=oid,
            letra=letra,
            tipo=tipo,
            ambitos=tuple(ambitos),
            texto=str(campos["texto"]),
        )
    return observaciones


def obs_por_letra(observaciones: dict[str, Observacion]) -> dict[str, Observacion]:
    return {o.letra: o for o in observaciones.values() if o.letra}


def texto_observacion(obs: Observacion, linea: Linea) -> str:
    """Texto literal que verá el cliente para `obs`, con `{telefono}`
    sustituido por el `telefono_demanda` de `linea` cuando lo hay. No hace
    nada si el texto no tiene el marcador o la línea no define teléfono."""
    if "{telefono}" in obs.texto and linea.telefono_demanda:
        return obs.texto.replace("{telefono}", linea.telefono_demanda)
    return obs.texto
