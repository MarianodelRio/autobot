"""Validación de un directorio `horarios/` completo: parser y validador único.

Único módulo que interpreta el formato de horarios/. Lo usan `tools/bus`, los
tests y el loader al arrancar el bot. Ninguna otra parte del código vuelve a
parsear estos ficheros.

`validar(directorio)` nunca lanza una excepción para un error de negocio
esperado (parada sin definir, horas que retroceden, etc.): esos casos entran
en la lista de errores del `Resultado`. Solo se propagan excepciones ante
fallos verdaderamente inesperados de E/S (por ejemplo, que `horarios/` no
exista).
"""

from __future__ import annotations

from pathlib import Path

from packs.bus.formato.buses import InfoViaje, avisos_mismo_bus, validar_buses
from packs.bus.formato.calendario import validar_calendario
from packs.bus.formato.comun import PREFIJO_LINEA, SUFIJO_LINEA_MARGEN, validar_id_de_canal
from packs.bus.formato.linea import LINEA_ID_RE, validar_linea
from packs.bus.formato.localidades import (
    validar_localidades_paradas,
    validar_localidades_pendientes,
    validar_no_vendibles,
    validar_pendientes_paradas,
)
from packs.bus.formato.normalizar import normalizar
from packs.bus.formato.observaciones import validar_observaciones
from packs.bus.formato.yaml_io import cargar_yaml
from packs.bus.modelo import Linea, Modelo, Resultado


def validar(directorio: Path | str) -> Resultado:
    """Valida `horarios/` al completo y devuelve (modelo, errores, avisos).

    No lanza excepciones para errores de negocio esperados: solo las lanzaría
    ante un fallo de E/S catastrófico no capturado explícitamente.
    """
    directorio = Path(directorio)
    errores: list[str] = []
    avisos: list[str] = []

    paradas_path = directorio / "paradas.yaml"
    observaciones_path = directorio / "observaciones.yaml"
    lineas_dir = directorio / "lineas"

    datos_paradas = cargar_yaml(paradas_path, errores)
    localidades, paradas = validar_localidades_paradas(
        datos_paradas or {}, paradas_path, errores, avisos
    )
    pendientes_paradas = validar_pendientes_paradas(
        datos_paradas or {}, paradas_path, errores, avisos
    )
    no_vendibles = validar_no_vendibles(datos_paradas or {}, paradas_path, localidades, errores)

    datos_observaciones = cargar_yaml(observaciones_path, errores)
    observaciones = validar_observaciones(datos_observaciones or {}, observaciones_path, errores)

    calendario = validar_calendario(directorio, errores, avisos, localidades)

    lineas: dict[str, Linea] = {}
    paradas_usadas: set[str] = set()
    infos_viaje: list[InfoViaje] = []
    if lineas_dir.is_dir():
        for path in sorted(lineas_dir.glob("*.yaml")):
            lid = path.stem
            if not LINEA_ID_RE.match(lid):
                errores.append(
                    f"{path}: id de línea inválido '{lid}' (el nombre del "
                    "fichero solo puede tener minúsculas sin tilde, dígitos "
                    "y guiones)"
                )
            validar_id_de_canal(
                errores,
                path,
                "línea",
                lid,
                len(PREFIJO_LINEA) + len(SUFIJO_LINEA_MARGEN),
            )
            datos_linea = cargar_yaml(path, errores)
            if datos_linea is None:
                continue
            linea = validar_linea(
                lid,
                datos_linea,
                path,
                paradas,
                observaciones,
                errores,
                avisos,
                infos_viaje,
            )
            if linea is not None:
                lineas[lid] = linea
                for viaje in linea.viajes:
                    for paso in viaje.pasos:
                        paradas_usadas.add(paso.parada)
    else:
        errores.append(f"{lineas_dir}: no existe el directorio de líneas")

    titulos_vistos: dict[str, list[str]] = {}
    for lid, linea in lineas.items():
        titulos_vistos.setdefault(normalizar(linea.titulo), []).append(lid)
    for titulo_norm, lids in sorted(titulos_vistos.items()):
        if len(lids) > 1:
            ficheros = ", ".join(str(lineas_dir / f"{x}.yaml") for x in sorted(lids))
            errores.append(
                f"{lineas_dir}: las líneas {sorted(lids)} tienen el mismo "
                f"título en el bot ('{titulo_norm}'): {ficheros}"
            )

    validar_localidades_pendientes(
        paradas_path,
        localidades,
        paradas,
        observaciones,
        pendientes_paradas,
        errores,
        avisos,
    )
    validar_buses(infos_viaje, paradas, localidades, errores)
    avisos_mismo_bus(infos_viaje, paradas, lineas, avisos)

    paradas_sin_usar = sorted(set(paradas.keys()) - paradas_usadas)
    if paradas_sin_usar:
        avisos.append(f"Paradas definidas que ninguna línea usa: {paradas_sin_usar}")

    # La misma fila de avisos cubre "paradas o localidades
    # definidas que ninguna línea usa". Una localidad está en uso si alguna de
    # sus paradas físicas aparece en algún viaje.
    localidades_usadas = {
        paradas[codigo].localidad for codigo in paradas_usadas if codigo in paradas
    }
    localidades_sin_usar = sorted(
        lid
        for lid, loc in localidades.items()
        if lid not in localidades_usadas and loc.pendiente is None
    )
    if localidades_sin_usar:
        avisos.append(f"Localidades definidas que ninguna línea usa: {localidades_sin_usar}")

    # Un par no vendible que ninguna línea conecta no sirve de nada: aviso.
    pares_conectados: set[frozenset[str]] = set()
    for linea in lineas.values():
        for viaje in linea.viajes:
            locs = [
                paradas[paso.parada].localidad for paso in viaje.pasos if paso.parada in paradas
            ]
            for i, loc_i in enumerate(locs):
                for loc_j in locs[i + 1 :]:
                    if loc_i != loc_j:
                        pares_conectados.add(frozenset((loc_i, loc_j)))
    for par in sorted(no_vendibles, key=lambda p: sorted(p)):
        if par not in pares_conectados:
            avisos.append(
                f"{paradas_path}: 'no_vendibles' {sorted(par)}: ninguna línea conecta ese par"
            )

    if calendario is not None:
        for loc_id in sorted(calendario.festivos_locales):
            if loc_id in localidades and loc_id not in localidades_usadas:
                avisos.append(
                    f"{directorio / 'calendario.yaml'}: 'festivos_locales' de "
                    f"'{loc_id}': ninguna línea usa esa localidad, no se "
                    "aplican a ninguna"
                )

    if errores:
        return Resultado(modelo=None, errores=errores, avisos=avisos)

    modelo = Modelo(
        localidades=localidades,
        paradas=paradas,
        observaciones=observaciones,
        lineas=lineas,
        pendientes=pendientes_paradas,
        no_vendibles=no_vendibles,
        calendario=calendario,
    )
    return Resultado(modelo=modelo, errores=errores, avisos=avisos)
