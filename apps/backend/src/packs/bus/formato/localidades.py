"""`paradas.yaml`: localidades, paradas, pendientes y pares no vendibles."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from packs.bus.formato.comun import PENDIENTE_RE, PREFIJO_LOC, validar_id_de_canal
from packs.bus.formato.normalizar import normalizar
from packs.bus.formato.yaml_io import claves_desconocidas
from packs.bus.modelo import Localidad, Observacion, Parada

CODIGO_PARADA_RE = re.compile(r"^[A-Z]{3}$")

# Campos permitidos de paradas.yaml: todo lo demás es un error (suele ser un
# nombre con coma sin comillas dentro de `{ ... }`).
CAMPOS_PARADAS_TOPE = {"localidades", "paradas", "pendientes", "no_vendibles"}
CAMPOS_LOCALIDAD = {"nombre", "alias", "pendiente", "ver", "minutos", "aviso"}
CAMPOS_PARADA = {"nombre", "localidad"}


def _validar_alias(
    lid: str, campos: dict[str, Any], nombre_norm: str, path: Path, errores: list[str]
) -> tuple[str, ...]:
    alias_raw = campos.get("alias", []) or []
    if not isinstance(alias_raw, list) or any(not isinstance(a, str) for a in alias_raw):
        errores.append(
            f"{path}: localidad '{lid}': 'alias' debe ser una lista de cadenas ({alias_raw!r})"
        )
        alias_raw = []
    vistos: set[str] = set()
    for a in alias_raw:
        a_norm = normalizar(a)
        if a_norm == "":
            errores.append(
                f"{path}: localidad '{lid}': el alias '{a}' normaliza a una cadena vacía"
            )
            continue
        if a_norm in vistos:
            errores.append(
                f"{path}: localidad '{lid}': el alias '{a}' está "
                "repetido (normaliza igual que otro alias de la misma "
                "localidad)"
            )
            continue
        vistos.add(a_norm)
        if a_norm == nombre_norm:
            errores.append(
                f"{path}: localidad '{lid}': el alias '{a}' coincide con "
                "el propio nombre de la localidad"
            )
    return tuple(str(a) for a in alias_raw)


def _validar_campos_pendiente(
    lid: str, campos: dict[str, Any], path: Path, errores: list[str]
) -> tuple[str | None, str | None, int | None, str | None]:
    """`pendiente`, `ver`, `minutos` y `aviso` de una localidad: o van los
    cuatro juntos (aviso es opcional) o no va ninguno."""
    pendiente = campos.get("pendiente")
    ver = campos.get("ver")
    minutos = campos.get("minutos")
    aviso = campos.get("aviso")
    if pendiente is not None:
        pendiente = str(pendiente)
        if not PENDIENTE_RE.match(pendiente):
            errores.append(
                f"{path}: localidad '{lid}': pendiente inválido "
                f"'{pendiente}' (debe cumplir P\\d{{2}})"
            )
        if ver is None:
            errores.append(
                f"{path}: localidad '{lid}': 'pendiente' sin 'ver' "
                "(localidad en cuyo lugar se consulta)"
            )
        if minutos is None:
            errores.append(
                f"{path}: localidad '{lid}': 'pendiente' sin 'minutos' "
                "(distancia a la localidad 'ver')"
            )
        elif isinstance(minutos, bool) or not isinstance(minutos, int) or not 1 <= minutos <= 60:
            errores.append(
                f"{path}: localidad '{lid}': 'minutos' debe ser un entero "
                f"entre 1 y 60 ({minutos!r})"
            )
            minutos = None
    else:
        if ver is not None:
            errores.append(f"{path}: localidad '{lid}': 'ver' sin 'pendiente'")
        if minutos is not None:
            errores.append(f"{path}: localidad '{lid}': 'minutos' sin 'pendiente'")
        if aviso is not None:
            errores.append(f"{path}: localidad '{lid}': 'aviso' sin 'pendiente'")
        ver = minutos = aviso = None
    return (
        pendiente,
        None if ver is None else str(ver),
        minutos,
        None if aviso is None else str(aviso),
    )


def _validar_localidad(lid: str, campos: Any, path: Path, errores: list[str]) -> Localidad | None:
    if isinstance(campos, dict):
        claves_desconocidas(
            campos,
            CAMPOS_LOCALIDAD,
            f"localidad '{lid}'",
            path,
            errores,
            ignorar={"zona"},
        )
    if not isinstance(campos, dict) or "nombre" not in campos:
        errores.append(f"{path}: localidad '{lid}' sin 'nombre'")
        return None
    if "zona" in campos:
        errores.append(
            f"{path}: localidad '{lid}': campo obsoleto 'zona' (los pueblos se agrupan por línea)"
        )
    validar_id_de_canal(errores, path, "localidad", lid, len(PREFIJO_LOC))

    nombre_norm = normalizar(str(campos["nombre"]))
    alias = _validar_alias(lid, campos, nombre_norm, path, errores)
    pendiente, ver, minutos, aviso = _validar_campos_pendiente(lid, campos, path, errores)
    return Localidad(
        id=lid,
        nombre=str(campos["nombre"]),
        alias=alias,
        pendiente=pendiente,
        ver=ver,
        minutos=minutos,
        aviso=aviso,
    )


def _validar_nombres_unicos(
    localidades: dict[str, Localidad], path: Path, errores: list[str]
) -> None:
    """Dos localidades cuyo nombre normalizado coincide es una ambigüedad no
    declarada (a diferencia de un alias compartido, que se avisa aparte):
    error, no aviso."""
    nombre_a_lids: dict[str, list[str]] = {}
    for lid, loc in localidades.items():
        nombre_a_lids.setdefault(normalizar(loc.nombre), []).append(lid)
    for nombre_norm, lids in nombre_a_lids.items():
        if len(lids) > 1:
            errores.append(
                f"{path}: localidades {sorted(lids)} tienen el mismo nombre "
                f"normalizado ('{nombre_norm}'), sin declarar cómo distinguirlas"
            )


def _validar_paradas(
    datos_paradas: dict[str, Any],
    path: Path,
    localidades: dict[str, Localidad],
    errores: list[str],
) -> dict[str, Parada]:
    paradas: dict[str, Parada] = {}
    paradas_raw = datos_paradas.get("paradas")
    if not isinstance(paradas_raw, dict):
        errores.append(f"{path}: falta el campo obligatorio 'paradas' (mapa)")
        paradas_raw = {}
    for codigo, campos in paradas_raw.items():
        if not CODIGO_PARADA_RE.match(codigo):
            errores.append(
                f"{path}: código de parada inválido '{codigo}' (deben ser 3 letras mayúsculas)"
            )
            continue
        if isinstance(campos, dict):
            claves_desconocidas(campos, CAMPOS_PARADA, f"parada '{codigo}'", path, errores)
        if not isinstance(campos, dict) or "nombre" not in campos or "localidad" not in campos:
            errores.append(f"{path}: parada '{codigo}' sin 'nombre' o 'localidad'")
            continue
        localidad_id = campos["localidad"]
        if localidad_id not in localidades:
            errores.append(
                f"{path}: parada '{codigo}' referencia una localidad sin definir ('{localidad_id}')"
            )
        paradas[codigo] = Parada(
            codigo=codigo, nombre=str(campos["nombre"]), localidad=localidad_id
        )
    return paradas


def _validar_paradas_contra_localidades(
    paradas: dict[str, Parada],
    localidades: dict[str, Localidad],
    path: Path,
    errores: list[str],
) -> None:
    """Una parada cuyo nombre normalizado coincide con el de OTRA localidad
    (no la suya) confundiría al matcher: error, no aviso."""
    for codigo, parada in paradas.items():
        if parada.localidad not in localidades:
            continue
        parada_norm = normalizar(parada.nombre)
        for lid, loc in localidades.items():
            if lid == parada.localidad:
                continue
            if normalizar(loc.nombre) == parada_norm:
                errores.append(
                    f"{path}: parada '{codigo}' ('{parada.nombre}') coincide "
                    f"con el nombre de la localidad '{lid}', distinta de la "
                    f"suya ('{parada.localidad}')"
                )


def _avisar_ambiguedades(localidades: dict[str, Localidad], path: Path, avisos: list[str]) -> None:
    """Ambigüedades declaradas (aviso, no error): un nombre o alias compartido
    por varias localidades, o un alias que coincide con el nombre de otra
    (caso real: dos localidades con el mismo nombre de uso común)."""
    mapa_claves: dict[str, set[str]] = {}
    for lid, loc in localidades.items():
        claves = {normalizar(loc.nombre)} | {normalizar(a) for a in loc.alias}
        for clave in claves:
            if clave == "":
                continue
            mapa_claves.setdefault(clave, set()).add(lid)
    for clave, lids_clave in sorted(mapa_claves.items()):
        if len(lids_clave) > 1:
            avisos.append(
                f"{path}: ambigüedad declarada: '{clave}' es nombre o alias "
                f"de varias localidades {sorted(lids_clave)}"
            )


def validar_localidades_paradas(
    datos_paradas: dict[str, Any], path: Path, errores: list[str], avisos: list[str]
) -> tuple[dict[str, Localidad], dict[str, Parada]]:
    claves_desconocidas(
        datos_paradas,
        CAMPOS_PARADAS_TOPE,
        "paradas.yaml",
        path,
        errores,
        ignorar={"zonas"},
    )
    if "zonas" in datos_paradas:
        errores.append(f"{path}: campo obsoleto 'zonas' (los pueblos se agrupan por línea)")

    localidades_raw = datos_paradas.get("localidades")
    if not isinstance(localidades_raw, dict):
        errores.append(f"{path}: falta el campo obligatorio 'localidades' (mapa)")
        localidades_raw = {}
    localidades: dict[str, Localidad] = {}
    for lid, campos in localidades_raw.items():
        localidad = _validar_localidad(lid, campos, path, errores)
        if localidad is not None:
            localidades[lid] = localidad

    _validar_nombres_unicos(localidades, path, errores)
    paradas = _validar_paradas(datos_paradas, path, localidades, errores)
    _validar_paradas_contra_localidades(paradas, localidades, path, errores)
    _avisar_ambiguedades(localidades, path, avisos)
    return localidades, paradas


def validar_pendientes_paradas(
    datos_paradas: dict[str, Any], path: Path, errores: list[str], avisos: list[str]
) -> tuple[str, ...]:
    """Lee el campo opcional `pendientes:` de paradas.yaml:
    preguntas abiertas que no están ligadas a ninguna línea concreta (p.ej.
    la posición de una aldea en la ruta)."""
    raw = datos_paradas.get("pendientes", []) or []
    if not isinstance(raw, list):
        errores.append(f"{path}: 'pendientes' debe ser una lista")
        return ()
    validos: list[str] = []
    for p in raw:
        p = str(p)
        if not PENDIENTE_RE.match(p):
            errores.append(f"{path}: pendiente inválido '{p}' (debe cumplir P\\d{{2}})")
            continue
        validos.append(p)
        avisos.append(f"{path}: pendiente {p}")
    return tuple(validos)


def validar_localidades_pendientes(
    path: Path,
    localidades: dict[str, Localidad],
    paradas: dict[str, Parada],
    observaciones: dict[str, Observacion],
    pendientes_paradas: tuple[str, ...],
    errores: list[str],
    avisos: list[str],
) -> None:
    """Localidades pendientes: aldeas sin hora de paso propia.
    Cruza `pendiente`, `ver` y `aviso` con paradas, observaciones y la lista
    `pendientes:` de paradas.yaml."""
    for lid, loc in sorted(localidades.items()):
        if loc.pendiente is None:
            continue
        pre = f"{path}: localidad pendiente '{lid}'"
        if PENDIENTE_RE.match(loc.pendiente):
            if loc.pendiente not in pendientes_paradas:
                errores.append(f"{pre}: {loc.pendiente} no está en 'pendientes' de paradas.yaml")
            avisos.append(f"{path}: localidad pendiente '{lid}' ({loc.pendiente})")
        if loc.ver is not None:
            if loc.ver not in localidades:
                errores.append(f"{pre}: 'ver' referencia una localidad sin definir ('{loc.ver}')")
            elif loc.ver == lid:
                errores.append(f"{pre}: 'ver' apunta a sí misma")
            elif localidades[loc.ver].pendiente is not None:
                errores.append(f"{pre}: 'ver' apunta a otra localidad pendiente ('{loc.ver}')")
        con_paradas = sorted(c for c, p in paradas.items() if p.localidad == lid)
        if con_paradas:
            errores.append(f"{pre}: una localidad pendiente no puede tener paradas ({con_paradas})")
        if loc.aviso is not None:
            obs = observaciones.get(loc.aviso)
            if obs is None:
                errores.append(
                    f"{pre}: 'aviso' referencia una observación sin definir ('{loc.aviso}')"
                )
            elif obs.tipo != "aviso":
                errores.append(f"{pre}: 'aviso' '{loc.aviso}' no es una observación de tipo aviso")
            elif "viaje" not in obs.ambitos:
                errores.append(f"{pre}: 'aviso' '{loc.aviso}' no tiene ámbito 'viaje'")
            elif loc.minutos is not None and str(loc.minutos) not in obs.texto:
                avisos.append(
                    f"{pre}: el texto de la observación '{loc.aviso}' no "
                    f"contiene los minutos declarados ({loc.minutos})"
                )


def validar_no_vendibles(
    datos_paradas: dict[str, Any],
    path: Path,
    localidades: dict[str, Localidad],
    errores: list[str],
) -> frozenset[frozenset[str]]:
    """Lee el campo opcional `no_vendibles:` de paradas.yaml: lista de
    pares `[localidad, localidad]` entre los que no se venden billetes, en
    ningún sentido. Localidad sin definir, la misma localidad dos veces y par
    repetido (también invertido) son errores."""
    raw = datos_paradas.get("no_vendibles", []) or []
    if not isinstance(raw, list):
        errores.append(f"{path}: 'no_vendibles' debe ser una lista de pares")
        return frozenset()
    pares: set[frozenset[str]] = set()
    for par in raw:
        if not isinstance(par, list) or len(par) != 2:
            errores.append(
                f"{path}: 'no_vendibles' con elemento inválido {par!r} (se "
                "esperaba un par [localidad, localidad])"
            )
            continue
        a, b = str(par[0]), str(par[1])
        desconocidas = [x for x in (a, b) if x not in localidades]
        if desconocidas:
            errores.append(
                f"{path}: 'no_vendibles' [{a}, {b}] referencia localidad(es) "
                f"sin definir: {desconocidas}"
            )
            continue
        if a == b:
            errores.append(f"{path}: 'no_vendibles' [{a}, {b}]: la misma localidad dos veces")
            continue
        clave = frozenset((a, b))
        if clave in pares:
            errores.append(
                f"{path}: 'no_vendibles' [{a}, {b}] repetido (el orden no "
                "importa: [a, b] y [b, a] son el mismo par)"
            )
            continue
        pares.add(clave)
    return frozenset(pares)
