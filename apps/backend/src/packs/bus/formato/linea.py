"""Ficheros de línea (`lineas/<id>.yaml`): cabecera, temporadas, días y tablas de horarios."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.dates import minutes_of
from packs.bus.formato.buses import InfoViaje
from packs.bus.formato.comun import PENDIENTE_RE
from packs.bus.formato.observaciones import CONDICIONES_CONOCIDAS, obs_por_letra
from packs.bus.formato.tabla import BUS_ID_RE, CELDA_HORA_RE, FilaTabla, parse_tabla
from packs.bus.formato.temporadas import (
    DIAS_DEL_ANIO,
    DIAS_INDIVIDUALES,
    ESTADOS_DIA,
    GRUPOS_DIA,
    parse_temporada_rango,
)
from packs.bus.modelo import Linea, Observacion, Parada, Paso, Tabla, Temporada, Viaje

LINEA_ID_RE = re.compile(r"^[a-z0-9-]+$")
CAMPOS_LINEA_OBLIGATORIOS = {"nombre", "temporadas", "dias", "horarios"}
CAMPOS_LINEA_PERMITIDOS = CAMPOS_LINEA_OBLIGATORIOS | {
    "telefono_demanda",
    "avisos",
    "no_circula",
    "pendientes",
    "nombre_corto",
}
# Título de fila de una lista interactiva de WhatsApp.
MAX_TITULO_LINEA = 24


@dataclass
class _Contexto:
    """Lo que comparten las comprobaciones de un fichero de línea."""

    lid: str
    path: Path
    paradas: dict[str, Parada]
    observaciones: dict[str, Observacion]
    errores: list[str]
    avisos: list[str]
    infos_viaje: list[InfoViaje] | None = None


@dataclass
class _Tablas:
    """Resultado de validar las tablas de una línea."""

    viajes: list[Viaje]
    tablas: list[Tabla]
    clases_cubiertas: dict[str, set[str]]
    usa_a_demanda: bool = False


# ── cabecera ──────────────────────────────────────────────────────────────────


def _validar_nombre_corto(datos: dict[str, Any], ctx: _Contexto) -> str | None:
    """Valida `nombre` y `nombre_corto`; devuelve el `nombre_corto` válido."""
    path, errores = ctx.path, ctx.errores
    nombre = datos["nombre"]
    nombre_corto = datos.get("nombre_corto")
    if nombre_corto is not None:
        if not isinstance(nombre_corto, str) or nombre_corto.strip() == "":
            errores.append(f"{path}: 'nombre_corto' debe ser un texto no vacío ({nombre_corto!r})")
            nombre_corto = None
        elif len(nombre_corto) > MAX_TITULO_LINEA:
            errores.append(
                f"{path}: 'nombre_corto' ('{nombre_corto}') tiene "
                f"{len(nombre_corto)} caracteres; el máximo es "
                f"{MAX_TITULO_LINEA} (título de fila de WhatsApp)"
            )
            nombre_corto = None
    if nombre_corto is None and len(str(nombre)) > MAX_TITULO_LINEA:
        errores.append(
            f"{path}: el nombre de la línea ('{nombre}') tiene "
            f"{len(str(nombre))} caracteres (máximo {MAX_TITULO_LINEA} para el "
            "título de fila de WhatsApp): añade 'nombre_corto'"
        )
    return nombre_corto


def _validar_avisos_linea(avisos_linea: list[str], ctx: _Contexto) -> None:
    """Los avisos de línea deben ser observaciones de ámbito línea, existentes."""
    for oid in avisos_linea:
        obs = ctx.observaciones.get(oid)
        if obs is None:
            ctx.errores.append(
                f"{ctx.path}: aviso de línea '{oid}' sin definir en observaciones.yaml"
            )
        elif "linea" not in obs.ambitos:
            ctx.errores.append(
                f"{ctx.path}: observación '{oid}' usada en ámbito 'linea' pero no lo permite"
            )


# ── temporadas y días ─────────────────────────────────────────────────────────


def _validar_temporadas(
    datos: dict[str, Any], ctx: _Contexto
) -> tuple[list[Temporada], dict[str, frozenset[int]]]:
    """Cada temporada con rango válido, y que entre todas cubran el año sin solaparse."""
    path, errores = ctx.path, ctx.errores
    temporadas_raw = datos["temporadas"]
    if not isinstance(temporadas_raw, dict) or not temporadas_raw:
        errores.append(f"{path}: 'temporadas' debe ser un mapa no vacío")
        temporadas_raw = {}

    temporadas: list[Temporada] = []
    indices_temporada: dict[str, frozenset[int]] = {}
    cobertura = [0] * len(DIAS_DEL_ANIO)
    for nombre_temp, rango in temporadas_raw.items():
        indices = parse_temporada_rango(str(rango))
        if indices is None:
            errores.append(
                f"{path}: temporada '{nombre_temp}' con rango inválido '{rango}' "
                "(se esperaba 'DD/MM - DD/MM' o 'todo el año')"
            )
            continue
        for i in indices:
            cobertura[i] += 1
        temporadas.append(Temporada(nombre=nombre_temp, rango=str(rango)))
        indices_temporada[nombre_temp] = frozenset(indices)

    dias_sin_cubrir = sum(1 for c in cobertura if c == 0)
    dias_solapados = sum(1 for c in cobertura if c > 1)
    if dias_sin_cubrir:
        errores.append(f"{path}: las temporadas dejan {dias_sin_cubrir} día(s) del año sin cubrir")
    if dias_solapados:
        errores.append(f"{path}: las temporadas se solapan en {dias_solapados} día(s) del año")
    return temporadas, indices_temporada


def _validar_dias_de_temporada(
    nombre_temp: str, declaracion: dict[str, Any], ctx: _Contexto
) -> dict[str, str]:
    """Estado de cada clase de día de una temporada; cada clase se declara una vez."""
    path, errores = ctx.path, ctx.errores
    estado_por_clase: dict[str, str] = {}
    cobertura_clases: dict[str, int] = {c: 0 for c in DIAS_INDIVIDUALES}
    for clave, estado in declaracion.items():
        if clave not in GRUPOS_DIA:
            errores.append(f"{path}: temporada '{nombre_temp}': clave de día desconocida '{clave}'")
            continue
        if estado not in ESTADOS_DIA:
            errores.append(
                f"{path}: temporada '{nombre_temp}', día '{clave}': estado desconocido '{estado}'"
            )
            continue
        # En orden de semana: un frozenset no da un orden estable entre ejecuciones.
        for clase in sorted(GRUPOS_DIA[clave], key=DIAS_INDIVIDUALES.index):
            cobertura_clases[clase] += 1
            estado_por_clase[clase] = estado
            if estado == "sin_datos":
                ctx.avisos.append(
                    f"{path}: {ctx.lid}, temporada '{nombre_temp}', '{clase}': "
                    "sin datos (nunca se trata como sin servicio)"
                )
    no_declaradas = [c for c, n in cobertura_clases.items() if n == 0]
    declaradas_dos_veces = [c for c, n in cobertura_clases.items() if n > 1]
    if no_declaradas:
        errores.append(
            f"{path}: temporada '{nombre_temp}': clase(s) de día sin declarar: {no_declaradas}"
        )
    if declaradas_dos_veces:
        errores.append(
            f"{path}: temporada '{nombre_temp}': clase(s) de día declaradas "
            f"dos veces: {declaradas_dos_veces}"
        )
    return estado_por_clase


def _validar_dias(
    datos: dict[str, Any], nombres_temporada: set[str], ctx: _Contexto
) -> dict[str, dict[str, str]]:
    """`dias`: estado de cada clase de día, por temporada."""
    dias_raw = datos["dias"]
    dias_estado: dict[str, dict[str, str]] = {}
    if not isinstance(dias_raw, dict):
        ctx.errores.append(f"{ctx.path}: 'dias' debe ser un mapa temporada -> claves de día")
        dias_raw = {}

    for nombre_temp in nombres_temporada:
        declaracion = dias_raw.get(nombre_temp)
        if not isinstance(declaracion, dict):
            ctx.errores.append(f"{ctx.path}: la temporada '{nombre_temp}' no declara 'dias'")
            dias_estado[nombre_temp] = {}
            continue
        dias_estado[nombre_temp] = _validar_dias_de_temporada(nombre_temp, declaracion, ctx)
    return dias_estado


# ── filas de una tabla ────────────────────────────────────────────────────────


def _validar_obs_de_parada(
    letras: str, codigo: str, pre: str, ctx: _Contexto, por_letra: dict[str, Observacion]
) -> tuple[list[str], bool]:
    """Observaciones (por letra) de una celda de hora; indica si alguna es `a_demanda`."""
    ids: list[str] = []
    a_demanda = False
    for letra in letras:
        obs = por_letra.get(letra)
        if obs is None:
            ctx.errores.append(f"{pre}: letra de observación sin definir '{letra}' en '{codigo}'")
            continue
        if "parada" not in obs.ambitos:
            ctx.errores.append(
                f"{pre}: observación '{obs.id}' usada en ámbito 'parada' pero no lo permite"
            )
            continue
        if obs.tipo == "condicion" and obs.id not in CONDICIONES_CONOCIDAS:
            ctx.errores.append(f"{pre}: condición '{obs.id}' que el motor no sabe aplicar")
            continue
        if obs.id == "a_demanda":
            a_demanda = True
        ids.append(obs.id)
    return ids, a_demanda


def _validar_llegada_salida(
    codigo: str,
    llegada_txt: str,
    salida_txt: str,
    es_extremo: bool,
    pre: str,
    errores: list[str],
) -> bool:
    """Una celda `llegada>salida`: solo en paradas intermedias y con la llegada
    anterior a la salida. Devuelve False si la celda invalida la fila."""
    llegada_min = minutes_of(llegada_txt)
    salida_min = minutes_of(salida_txt)
    if es_extremo:
        errores.append(
            f"{pre}: llegada y salida solo en una parada intermedia del viaje ('{codigo}')"
        )
        return False
    if salida_min == llegada_min:
        errores.append(f"{pre}: misma hora dos veces en '{codigo}'; escribe una sola")
        return False
    if salida_min < llegada_min:
        errores.append(
            f"{pre}: la llegada debe ser anterior a la salida en '{codigo}' "
            f"({llegada_txt}>{salida_txt})"
        )
        return False
    return True


def _validar_celdas(
    cabecera: list[str],
    fila: FilaTabla,
    pre: str,
    ctx: _Contexto,
    por_letra: dict[str, Observacion],
) -> tuple[list[Paso], bool, bool]:
    """Pasos de una fila. Devuelve (pasos, fila_valida, usa_a_demanda)."""
    errores = ctx.errores
    pasos: list[Paso] = []
    # (llegada, salida) en minutos de cada celda con hora válida
    horas_validas: list[tuple[int, int]] = []
    fila_valida = True
    usa_a_demanda = False
    indices_con_valor = [i for i, v in enumerate(fila.valores) if v != "-"]
    primero = indices_con_valor[0] if indices_con_valor else -1
    ultimo = indices_con_valor[-1] if indices_con_valor else -1
    for indice, (codigo, valor) in enumerate(zip(cabecera, fila.valores, strict=True)):
        if valor == "-":
            continue
        m = CELDA_HORA_RE.match(valor)
        if not m:
            errores.append(f"{pre}: valor inválido '{valor}' en '{codigo}'")
            fila_valida = False
            continue
        llegada_txt = m.group(1)
        salida_txt = m.group(2) or llegada_txt
        if m.group(2) is not None and not _validar_llegada_salida(
            codigo, llegada_txt, salida_txt, indice in (primero, ultimo), pre, errores
        ):
            fila_valida = False
        llegada_min = minutes_of(llegada_txt)
        if horas_validas and llegada_min < horas_validas[-1][1]:
            errores.append(f"{pre}: las horas retroceden en '{codigo}' ({llegada_txt})")
        horas_validas.append((llegada_min, minutes_of(salida_txt)))

        obs_parada, a_demanda = _validar_obs_de_parada(m.group(3), codigo, pre, ctx, por_letra)
        usa_a_demanda = usa_a_demanda or a_demanda
        pasos.append(
            Paso(
                parada=codigo,
                llegada=llegada_txt,
                salida=salida_txt,
                observaciones=tuple(obs_parada),
            )
        )

    if fila_valida and len(horas_validas) < 2:
        errores.append(f"{pre}: el viaje tiene menos de 2 horas")
    return pasos, fila_valida, usa_a_demanda


def _validar_obs_de_viaje(fila: FilaTabla, pre: str, ctx: _Contexto) -> list[str]:
    ids: list[str] = []
    for tok in fila.obs_viaje:
        obs = ctx.observaciones.get(tok)
        if obs is None:
            ctx.errores.append(f"{pre}: observación de viaje sin definir '{tok}'")
            continue
        if "viaje" not in obs.ambitos:
            ctx.errores.append(
                f"{pre}: observación '{tok}' usada en ámbito 'viaje' pero no lo permite"
            )
            continue
        if obs.tipo == "condicion" and obs.id not in CONDICIONES_CONOCIDAS:
            ctx.errores.append(f"{pre}: condición '{tok}' que el motor no sabe aplicar")
            continue
        ids.append(obs.id)
    return ids


def _validar_pendientes_de_fila(fila: FilaTabla, pre: str, ctx: _Contexto) -> list[str]:
    pendientes: list[str] = []
    for tok in fila.pendientes:
        if not PENDIENTE_RE.match(tok):
            ctx.errores.append(f"{pre}: pendiente inválido '{tok}'")
            continue
        pendientes.append(tok)
        ctx.avisos.append(f"{pre}: pendiente {tok}")
    return pendientes


def _validar_bus_de_fila(fila: FilaTabla, pre: str, errores: list[str]) -> str | None:
    if len(fila.bus) > 1:
        errores.append(
            f"{pre}: más de un 'bus:' en el mismo viaje ({['bus:' + b for b in fila.bus]})"
        )
    for candidato in fila.bus[:1]:
        if BUS_ID_RE.match(candidato):
            return candidato
        errores.append(
            f"{pre}: identificador de autobús inválido 'bus:{candidato}' "
            "(solo minúsculas, cifras y guiones)"
        )
    return None


# ── tablas ────────────────────────────────────────────────────────────────────


def _validar_tabla(
    entrada: dict[str, Any],
    etiqueta_tabla: str,
    tablas_ya: _Tablas,
    ctx: _Contexto,
    nombres_temporada: set[str],
    indices_temporada: dict[str, frozenset[int]],
    por_letra: dict[str, Observacion],
) -> None:
    """Una entrada de `horarios:`; añade su tabla y sus viajes a `tablas_ya`."""
    errores = ctx.errores
    temporada_e = entrada["temporada"]
    dias_e = entrada["dias"]

    if temporada_e not in nombres_temporada:
        errores.append(f"{etiqueta_tabla}: referencia una temporada sin declarar")
        return
    if dias_e not in GRUPOS_DIA:
        errores.append(f"{etiqueta_tabla}: clave de día desconocida '{dias_e}'")
        return

    cabecera, filas = parse_tabla(entrada["tabla"])
    if cabecera is None:
        errores.append(f"{etiqueta_tabla}: tabla vacía")
        return
    if len(cabecera) < 2:
        errores.append(f"{etiqueta_tabla}: la cabecera debe tener al menos 2 paradas")
    if len(cabecera) != len(set(cabecera)):
        errores.append(f"{etiqueta_tabla}: paradas repetidas en la cabecera {cabecera}")
    for codigo in cabecera:
        if codigo not in ctx.paradas:
            errores.append(f"{etiqueta_tabla}: código de parada sin definir '{codigo}'")

    tabla_actual = Tabla(
        linea=ctx.lid,
        temporada=temporada_e,
        dias=dias_e,
        paradas=tuple(cabecera),
        posicion=len(tablas_ya.tablas),
    )
    tablas_ya.tablas.append(tabla_actual)

    for fila in filas:
        pre = f"{etiqueta_tabla}, fila {fila.numero}"
        if len(fila.valores) != len(cabecera):
            errores.append(
                f"{pre}: {len(fila.valores)} valores, se esperaban {len(cabecera)} (uno por parada)"
            )
            continue

        pasos, fila_valida, a_demanda = _validar_celdas(cabecera, fila, pre, ctx, por_letra)
        tablas_ya.usa_a_demanda = tablas_ya.usa_a_demanda or a_demanda
        obs_viaje_ids = _validar_obs_de_viaje(fila, pre, ctx)
        pendientes_fila = _validar_pendientes_de_fila(fila, pre, ctx)
        bus_id = _validar_bus_de_fila(fila, pre, errores)

        viaje_nuevo = Viaje(
            linea=ctx.lid,
            temporada=temporada_e,
            dias=dias_e,
            tabla=tabla_actual,
            observaciones=tuple(obs_viaje_ids),
            pendientes=tuple(pendientes_fila),
            pasos=tuple(pasos),
            bus=bus_id,
        )
        tablas_ya.viajes.append(viaje_nuevo)
        if ctx.infos_viaje is not None:
            ctx.infos_viaje.append(
                InfoViaje(
                    viaje=viaje_nuevo,
                    ruta=str(ctx.path),
                    etiqueta=pre,
                    indices=indices_temporada.get(temporada_e, frozenset()),
                    clases=GRUPOS_DIA[dias_e],
                )
            )

    tablas_ya.clases_cubiertas.setdefault(temporada_e, set()).update(GRUPOS_DIA[dias_e])


def _etiquetas_de_tablas(horarios_raw: list[Any], path: Path) -> dict[int, str]:
    """Etiqueta de cada entrada de `horarios:` para los mensajes.

    Varias tablas de la misma línea pueden compartir temporada+dias (p.ej.
    ida y vuelta ambas anual/sábado): sin más información en el esquema (el
    formato no declara un campo de sentido por tabla), se numeran
    "tabla N de M" para que los avisos/errores de cada una sean
    distinguibles. Las entradas incompletas no tienen etiqueta."""
    completas = [
        (i, (e["temporada"], e["dias"]))
        for i, e in enumerate(horarios_raw)
        if isinstance(e, dict) and {"temporada", "dias", "tabla"} <= set(e.keys())
    ]
    conteo: dict[tuple[Any, Any], int] = {}
    for _, clave in completas:
        conteo[clave] = conteo.get(clave, 0) + 1
    visto: dict[tuple[Any, Any], int] = {}
    etiquetas: dict[int, str] = {}
    for i, clave in completas:
        temporada_e, dias_e = clave
        if conteo[clave] > 1:
            visto[clave] = visto.get(clave, 0) + 1
            etiquetas[i] = (
                f"{path} [temporada={temporada_e}, dias={dias_e}, "
                f"tabla {visto[clave]} de {conteo[clave]}]"
            )
        else:
            etiquetas[i] = f"{path} [temporada={temporada_e}, dias={dias_e}]"
    return etiquetas


def _validar_tablas(
    datos: dict[str, Any],
    ctx: _Contexto,
    nombres_temporada: set[str],
    indices_temporada: dict[str, frozenset[int]],
    por_letra: dict[str, Observacion],
) -> _Tablas:
    horarios_raw = datos["horarios"]
    if not isinstance(horarios_raw, list) or not horarios_raw:
        ctx.errores.append(f"{ctx.path}: 'horarios' debe ser una lista no vacía de tablas")
        horarios_raw = []

    resultado = _Tablas(
        viajes=[], tablas=[], clases_cubiertas={t: set() for t in nombres_temporada}
    )
    etiquetas = _etiquetas_de_tablas(horarios_raw, ctx.path)
    for i, entrada in enumerate(horarios_raw):
        if i not in etiquetas:
            ctx.errores.append(
                f"{ctx.path}: entrada de 'horarios' incompleta (faltan temporada/dias/tabla)"
            )
            continue
        _validar_tabla(
            entrada, etiquetas[i], resultado, ctx, nombres_temporada, indices_temporada, por_letra
        )
    return resultado


def _validar_tablas_distinguibles(tablas: list[Tabla], ctx: _Contexto) -> None:
    """Dos tablas con la misma temporada, días y extremos de cabecera serían
    indistinguibles para el diff y para la vista de revisión: a diferencia de
    "tabla N de M" (que solo numera avisos), esto es un error porque
    probablemente son la misma tabla duplicada por error."""
    firmas_tabla: dict[tuple[str, str, str, str], list[Tabla]] = {}
    for t in tablas:
        if len(t.paradas) < 2:
            continue
        firma = (t.temporada, t.dias, t.paradas[0], t.paradas[-1])
        firmas_tabla.setdefault(firma, []).append(t)
    for (temporada_f, dias_f, primera_f, ultima_f), lista in firmas_tabla.items():
        if len(lista) > 1:
            ctx.errores.append(
                f"{ctx.path}: {len(lista)} tablas con temporada '{temporada_f}', "
                f"días '{dias_f}', de '{primera_f}' a '{ultima_f}' (deben "
                "distinguirse por sus extremos; si no, son la misma tabla "
                "duplicada)"
            )


def _validar_horarios_cubiertos(
    dias_estado: dict[str, dict[str, str]], clases_cubiertas: dict[str, set[str]], ctx: _Contexto
) -> None:
    """Toda clase con estado 'horario' tiene alguna tabla que la cubre."""
    for nombre_temp, estado_por_clase in dias_estado.items():
        for clase, estado in estado_por_clase.items():
            if estado == "horario" and clase not in clases_cubiertas.get(nombre_temp, set()):
                ctx.errores.append(
                    f"{ctx.path}: temporada '{nombre_temp}', clase '{clase}': "
                    "estado 'horario' sin ninguna tabla que la cubra"
                )


# ── línea completa ────────────────────────────────────────────────────────────


def validar_linea(
    lid: str,
    datos: dict[str, Any],
    path: Path,
    paradas: dict[str, Parada],
    observaciones: dict[str, Observacion],
    errores: list[str],
    avisos: list[str],
    infos_viaje: list[InfoViaje] | None = None,
) -> Linea | None:
    campos_desconocidos = set(datos.keys()) - CAMPOS_LINEA_PERMITIDOS
    if campos_desconocidos:
        errores.append(f"{path}: campo(s) desconocido(s): {sorted(campos_desconocidos)}")
    campos_ausentes = CAMPOS_LINEA_OBLIGATORIOS - set(datos.keys())
    if campos_ausentes:
        errores.append(f"{path}: falta(n) campo(s) obligatorio(s): {sorted(campos_ausentes)}")
        return None

    ctx = _Contexto(lid, path, paradas, observaciones, errores, avisos, infos_viaje)
    nombre_corto = _validar_nombre_corto(datos, ctx)
    telefono_demanda = datos.get("telefono_demanda")
    avisos_linea = datos.get("avisos", []) or []
    no_circula = datos.get("no_circula", []) or []
    pendientes_linea = datos.get("pendientes", []) or []

    for p in pendientes_linea:
        if not PENDIENTE_RE.match(p):
            errores.append(f"{path}: pendiente inválido '{p}' (debe cumplir P\\d{{2}})")
    _validar_avisos_linea(avisos_linea, ctx)

    temporadas, indices_temporada = _validar_temporadas(datos, ctx)
    nombres_temporada = {t.nombre for t in temporadas}
    dias_estado = _validar_dias(datos, nombres_temporada, ctx)
    tablas = _validar_tablas(
        datos, ctx, nombres_temporada, indices_temporada, obs_por_letra(observaciones)
    )
    _validar_tablas_distinguibles(tablas.tablas, ctx)
    _validar_horarios_cubiertos(dias_estado, tablas.clases_cubiertas, ctx)

    if tablas.usa_a_demanda and not telefono_demanda:
        errores.append(f"{path}: se usa 'a_demanda' pero la línea no define 'telefono_demanda'")

    for p in pendientes_linea:
        if PENDIENTE_RE.match(p):
            avisos.append(f"{path}: {lid}: pendiente de línea {p}")

    return Linea(
        id=lid,
        nombre=str(datos["nombre"]),
        telefono_demanda=telefono_demanda,
        avisos=tuple(avisos_linea),
        no_circula=tuple(no_circula),
        temporadas=tuple(temporadas),
        dias=dias_estado,
        pendientes=tuple(pendientes_linea),
        viajes=tuple(tablas.viajes),
        tablas=tuple(tablas.tablas),
        nombre_corto=nombre_corto,
    )
