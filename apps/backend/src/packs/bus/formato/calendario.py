"""`calendario.yaml`: festivos y periodo escolar, con fechas de año real.

Nunca adivina: fecha inválida, rango invertido, festivo duplicado o fuera de
vigencia, campo desconocido o ausente, e inicio de curso posterior al fin son
errores concretos.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from packs.bus.formato.comun import PENDIENTE_RE
from packs.bus.formato.temporadas import INDICE_DIA
from packs.bus.formato.yaml_io import cargar_yaml
from packs.bus.modelo import Calendario, Localidad

# Fechas con año real (a diferencia de las temporadas de línea, que no lo
# llevan): parser distinto y sin relación con `parse_temporada_rango` /
# `DIAS_DEL_ANIO` (que son año-independientes y se reutilizan cada año).
FECHA_RE = re.compile(r"^(\d{2})/(\d{2})/(\d{4})$")
RANGO_FECHA_RE = re.compile(r"^(\d{2})/(\d{2})/(\d{4})\s*-\s*(\d{2})/(\d{2})/(\d{4})$")
DIA_MES_RE = re.compile(r"^(\d{2})/(\d{2})$")

CAMPOS_CALENDARIO_OBLIGATORIOS = {"vigencia", "festivos", "curso"}
CAMPOS_CALENDARIO_PERMITIDOS = CAMPOS_CALENDARIO_OBLIGATORIOS | {
    "pendientes",
    "sin_servicio_todas_las_lineas",
    "festivos_locales",
}
CAMPOS_CURSO_OBLIGATORIOS = {"inicio_clases", "fin_clases", "vacaciones", "no_lectivos"}


def _parse_fecha(txt: str) -> date | None:
    """Fecha con año real 'DD/MM/AAAA'. Distinto del rango año-independiente
    'DD/MM - DD/MM' de las temporadas de línea."""
    m = FECHA_RE.match(txt.strip())
    if not m:
        return None
    d, mo, y = (int(x) for x in m.groups())
    try:
        return date(y, mo, d)
    except ValueError:
        return None


def _parse_rango_fechas(txt: str) -> tuple[date, date] | None:
    m = RANGO_FECHA_RE.match(txt.strip())
    if not m:
        return None
    d1, m1, y1, d2, m2, y2 = (int(x) for x in m.groups())
    try:
        f1 = date(y1, m1, d1)
        f2 = date(y2, m2, d2)
    except ValueError:
        return None
    return f1, f2


@dataclass
class _Contexto:
    """Lo que comparten las comprobaciones de `calendario.yaml`."""

    path: Path
    errores: list[str]
    avisos: list[str]
    vigencia_inicio: date
    vigencia_fin: date
    vigencia_txt: str

    def en_vigencia(self, f: date, contexto: str) -> None:
        if f < self.vigencia_inicio or f > self.vigencia_fin:
            self.errores.append(
                f"{self.path}: {contexto} ({f.strftime('%d/%m/%Y')}) fuera de la "
                f"vigencia del calendario ('{self.vigencia_txt}')"
            )


def _validar_festivos(datos: dict[str, Any], ctx: _Contexto) -> dict[date, str]:
    festivos_raw = datos["festivos"]
    festivos: dict[date, str] = {}
    if not isinstance(festivos_raw, dict) or not festivos_raw:
        ctx.errores.append(f"{ctx.path}: 'festivos' debe ser un mapa no vacío")
        festivos_raw = {}
    for fecha_txt, nombre in festivos_raw.items():
        fecha = _parse_fecha(str(fecha_txt))
        if fecha is None:
            ctx.errores.append(
                f"{ctx.path}: festivo con fecha inválida '{fecha_txt}' (se esperaba 'DD/MM/AAAA')"
            )
            continue
        if fecha in festivos:
            ctx.errores.append(f"{ctx.path}: festivo duplicado '{fecha_txt}'")
            continue
        ctx.en_vigencia(fecha, f"festivo '{nombre}'")
        festivos[fecha] = str(nombre)
    return festivos


def _validar_fecha_de_curso(curso_raw: dict[str, Any], campo: str, ctx: _Contexto) -> date | None:
    if campo not in curso_raw:
        return None
    fecha = _parse_fecha(str(curso_raw[campo]))
    if fecha is None:
        ctx.errores.append(f"{ctx.path}: 'curso.{campo}' con fecha inválida '{curso_raw[campo]}'")
        return None
    ctx.en_vigencia(fecha, f"'curso.{campo}'")
    return fecha


def _validar_curso(
    datos: dict[str, Any], ctx: _Contexto
) -> tuple[date | None, date | None, list[tuple[date, date]], list[date]]:
    """`curso`: inicio y fin de clases, vacaciones y días no lectivos."""
    path, errores = ctx.path, ctx.errores
    curso_raw = datos["curso"]
    if not isinstance(curso_raw, dict):
        errores.append(f"{path}: 'curso' debe ser un mapa")
        curso_raw = {}
    campos_curso_desconocidos = set(curso_raw.keys()) - CAMPOS_CURSO_OBLIGATORIOS
    if campos_curso_desconocidos:
        errores.append(
            f"{path}: 'curso' tiene campo(s) desconocido(s): {sorted(campos_curso_desconocidos)}"
        )
    campos_curso_ausentes = CAMPOS_CURSO_OBLIGATORIOS - set(curso_raw.keys())
    if campos_curso_ausentes:
        errores.append(
            f"{path}: 'curso' no define campo(s) obligatorio(s): {sorted(campos_curso_ausentes)}"
        )

    inicio_clases = _validar_fecha_de_curso(curso_raw, "inicio_clases", ctx)
    fin_clases = _validar_fecha_de_curso(curso_raw, "fin_clases", ctx)
    if inicio_clases is not None and fin_clases is not None and inicio_clases > fin_clases:
        errores.append(
            f"{path}: 'curso.inicio_clases' ({inicio_clases.strftime('%d/%m/%Y')}) "
            f"es posterior a 'curso.fin_clases' ({fin_clases.strftime('%d/%m/%Y')})"
        )

    vacaciones_raw = curso_raw.get("vacaciones", [])
    vacaciones: list[tuple[date, date]] = []
    if not isinstance(vacaciones_raw, list):
        errores.append(f"{path}: 'curso.vacaciones' debe ser una lista")
        vacaciones_raw = []
    for rango_txt in vacaciones_raw:
        rango = _parse_rango_fechas(str(rango_txt))
        if rango is None:
            errores.append(f"{path}: 'curso.vacaciones' con rango inválido '{rango_txt}'")
            continue
        f1, f2 = rango
        if f2 < f1:
            errores.append(f"{path}: 'curso.vacaciones' con rango invertido '{rango_txt}'")
            continue
        ctx.en_vigencia(f1, f"'curso.vacaciones' ({rango_txt}), inicio")
        ctx.en_vigencia(f2, f"'curso.vacaciones' ({rango_txt}), fin")
        vacaciones.append((f1, f2))

    no_lectivos_raw = curso_raw.get("no_lectivos", [])
    no_lectivos: list[date] = []
    if not isinstance(no_lectivos_raw, list):
        errores.append(f"{path}: 'curso.no_lectivos' debe ser una lista")
        no_lectivos_raw = []
    for fecha_txt in no_lectivos_raw:
        fecha = _parse_fecha(str(fecha_txt))
        if fecha is None:
            errores.append(f"{path}: 'curso.no_lectivos' con fecha inválida '{fecha_txt}'")
            continue
        ctx.en_vigencia(fecha, "'curso.no_lectivos'")
        no_lectivos.append(fecha)
    return inicio_clases, fin_clases, vacaciones, no_lectivos


def _validar_festivos_locales(
    datos: dict[str, Any],
    ctx: _Contexto,
    localidades: dict[str, Localidad],
    festivos: dict[date, str],
) -> dict[str, dict[date, str]]:
    path, errores = ctx.path, ctx.errores
    festivos_locales_raw = datos.get("festivos_locales", {}) or {}
    festivos_locales: dict[str, dict[date, str]] = {}
    if not isinstance(festivos_locales_raw, dict):
        errores.append(f"{path}: 'festivos_locales' debe ser un mapa localidad -> fechas")
        festivos_locales_raw = {}
    for loc_id, mapa in festivos_locales_raw.items():
        loc_id = str(loc_id)
        if loc_id not in localidades:
            errores.append(
                f"{path}: 'festivos_locales' referencia una localidad sin definir ('{loc_id}')"
            )
            continue
        if not isinstance(mapa, dict) or not mapa:
            errores.append(
                f"{path}: 'festivos_locales.{loc_id}' debe ser un mapa "
                "'DD/MM/AAAA: nombre' no vacío"
            )
            continue
        de_la_localidad: dict[date, str] = {}
        for fecha_txt, nombre in mapa.items():
            fecha = _parse_fecha(str(fecha_txt))
            if fecha is None:
                errores.append(
                    f"{path}: 'festivos_locales.{loc_id}' con fecha inválida "
                    f"'{fecha_txt}' (se esperaba 'DD/MM/AAAA')"
                )
                continue
            if fecha in de_la_localidad:
                errores.append(
                    f"{path}: 'festivos_locales.{loc_id}' con fecha repetida '{fecha_txt}'"
                )
                continue
            ctx.en_vigencia(fecha, f"festivo local '{nombre}' de '{loc_id}'")
            if fecha in festivos:
                errores.append(
                    f"{path}: 'festivos_locales.{loc_id}': la fecha "
                    f"'{fecha_txt}' ya está en 'festivos' ('{festivos[fecha]}')"
                )
                continue
            de_la_localidad[fecha] = str(nombre)
        festivos_locales[loc_id] = de_la_localidad
    return festivos_locales


def _validar_sin_servicio_general(datos: dict[str, Any], ctx: _Contexto) -> set[tuple[int, int]]:
    """Días (mes, día) de todos los años sin servicio en ninguna línea."""
    path, errores = ctx.path, ctx.errores
    sin_servicio_raw = datos.get("sin_servicio_todas_las_lineas", []) or []
    sin_servicio_general: set[tuple[int, int]] = set()
    if not isinstance(sin_servicio_raw, list):
        errores.append(
            f"{path}: 'sin_servicio_todas_las_lineas' debe ser una lista de fechas 'DD/MM'"
        )
        sin_servicio_raw = []
    for dia_txt in sin_servicio_raw:
        m = DIA_MES_RE.match(str(dia_txt).strip())
        if m is None:
            errores.append(
                f"{path}: 'sin_servicio_todas_las_lineas' con fecha inválida "
                f"'{dia_txt}' (se esperaba 'DD/MM')"
            )
            continue
        dia_n, mes_n = int(m.group(1)), int(m.group(2))
        if (mes_n, dia_n) not in INDICE_DIA:
            errores.append(
                f"{path}: 'sin_servicio_todas_las_lineas' con fecha que no existe '{dia_txt}'"
            )
            continue
        if (mes_n, dia_n) in sin_servicio_general:
            errores.append(
                f"{path}: 'sin_servicio_todas_las_lineas' con fecha repetida '{dia_txt}'"
            )
            continue
        sin_servicio_general.add((mes_n, dia_n))
    return sin_servicio_general


def _validar_pendientes(datos: dict[str, Any], ctx: _Contexto) -> list[str]:
    path = ctx.path
    pendientes_raw = datos.get("pendientes", []) or []
    pendientes: list[str] = []
    if not isinstance(pendientes_raw, list):
        ctx.errores.append(f"{path}: 'pendientes' debe ser una lista")
        return pendientes
    for p in pendientes_raw:
        p = str(p)
        if not PENDIENTE_RE.match(p):
            ctx.errores.append(f"{path}: pendiente inválido '{p}' (debe cumplir P\\d{{2}})")
            continue
        pendientes.append(p)
        ctx.avisos.append(f"{path}: pendiente {p}")
    return pendientes


def _validar_vigencia(
    datos: dict[str, Any], path: Path, errores: list[str]
) -> tuple[date, date] | None:
    vigencia_raw = datos["vigencia"]
    rango_vigencia = _parse_rango_fechas(str(vigencia_raw))
    if rango_vigencia is None:
        errores.append(
            f"{path}: 'vigencia' con rango inválido '{vigencia_raw}' (se "
            "esperaba 'DD/MM/AAAA - DD/MM/AAAA')"
        )
        return None
    if rango_vigencia[1] < rango_vigencia[0]:
        errores.append(
            f"{path}: 'vigencia' con fecha de fin anterior a la de inicio ('{vigencia_raw}')"
        )
        return None
    return rango_vigencia


def validar_calendario(
    directorio: Path,
    errores: list[str],
    avisos: list[str],
    localidades: dict[str, Localidad],
) -> Calendario | None:
    """Valida `calendario.yaml`; `None` si no se puede construir el calendario."""
    path = directorio / "calendario.yaml"
    datos = cargar_yaml(path, errores)
    if datos is None:
        return None

    campos_desconocidos = set(datos.keys()) - CAMPOS_CALENDARIO_PERMITIDOS
    if campos_desconocidos:
        errores.append(f"{path}: campo(s) desconocido(s): {sorted(campos_desconocidos)}")
    campos_ausentes = CAMPOS_CALENDARIO_OBLIGATORIOS - set(datos.keys())
    if campos_ausentes:
        errores.append(f"{path}: falta(n) campo(s) obligatorio(s): {sorted(campos_ausentes)}")
        return None

    vigencia = _validar_vigencia(datos, path, errores)
    if vigencia is None:
        return None
    vigencia_inicio, vigencia_fin = vigencia
    ctx = _Contexto(path, errores, avisos, vigencia_inicio, vigencia_fin, str(datos["vigencia"]))

    festivos = _validar_festivos(datos, ctx)
    inicio_clases, fin_clases, vacaciones, no_lectivos = _validar_curso(datos, ctx)
    festivos_locales = _validar_festivos_locales(datos, ctx, localidades, festivos)
    sin_servicio_general = _validar_sin_servicio_general(datos, ctx)
    pendientes = _validar_pendientes(datos, ctx)

    if inicio_clases is None or fin_clases is None:
        return None

    return Calendario(
        vigencia_inicio=vigencia_inicio,
        vigencia_fin=vigencia_fin,
        festivos=festivos,
        inicio_clases=inicio_clases,
        fin_clases=fin_clases,
        vacaciones=tuple(vacaciones),
        no_lectivos=tuple(no_lectivos),
        pendientes=tuple(pendientes),
        sin_servicio_todas_las_lineas=frozenset(sin_servicio_general),
        festivos_locales=festivos_locales,
    )
