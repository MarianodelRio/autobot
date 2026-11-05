"""packs/bus/formato.py — parser + validador único de horarios/.

Único módulo que interpreta el formato de horarios/.
Lo usan `tools/validar.py`, `tools/formatear.py`, los tests y (fase 2) el
loader al arrancar el bot. Ninguna otra parte del código vuelve a parsear
estos ficheros.

`validar(directorio)` nunca lanza una excepción para un error de negocio
esperado (parada sin definir, horas que retroceden, etc.): esos casos entran
en la lista de errores del `Resultado`. Solo se propagan excepciones ante
fallos verdaderamente inesperados de E/S (por ejemplo, que `horarios/` no
exista).
"""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from core.text import normalize
from packs.bus.modelo import (
    Calendario,
    Linea,
    Localidad,
    Observacion,
    Parada,
    Paso,
    Tabla,
    Temporada,
    Viaje,
)

PENDIENTE_RE = re.compile(r"^P\d{2}$")
CODIGO_PARADA_RE = re.compile(r"^[A-Z]{3}$")
# Celda de hora: `HH:MM`, o `HH:MM>HH:MM` (llegada>salida en la misma parada,
# solo en paradas intermedias), seguida de letras de observación de parada.
_HH_MM = r"(?:[01]\d|2[0-3]):[0-5]\d"
CELDA_HORA_RE = re.compile(rf"^({_HH_MM})(?:>({_HH_MM}))?([A-Z]*)$")
BUS_ID_RE = re.compile(r"^[a-z0-9-]+$")
MARCADOR_RE = re.compile(r"\{([^}]*)\}")

DIAS_INDIVIDUALES = (
    "lunes",
    "martes",
    "miercoles",
    "jueves",
    "viernes",
    "sabado",
    "domingo",
    "festivos",
)

GRUPOS_DIA: dict[str, frozenset[str]] = {
    "lunes": frozenset({"lunes"}),
    "martes": frozenset({"martes"}),
    "miercoles": frozenset({"miercoles"}),
    "jueves": frozenset({"jueves"}),
    "viernes": frozenset({"viernes"}),
    "sabado": frozenset({"sabado"}),
    "domingo": frozenset({"domingo"}),
    "festivos": frozenset({"festivos"}),
    "lunes-viernes": frozenset({"lunes", "martes", "miercoles", "jueves", "viernes"}),
    "lunes-jueves": frozenset({"lunes", "martes", "miercoles", "jueves"}),
    "martes-viernes": frozenset({"martes", "miercoles", "jueves", "viernes"}),
    "sabados-domingos": frozenset({"sabado", "domingo"}),
    "domingos-festivos": frozenset({"domingo", "festivos"}),
    "sabados-domingos-festivos": frozenset({"sabado", "domingo", "festivos"}),
}

ESTADOS_DIA = {"horario", "sin_servicio", "sin_datos"}

# Temporadas con nombre público: solo estas se muestran al cliente como
# "horario de X" en la cabecera del resultado. Una temporada
# nueva con nombre propio exige ampliar esta tabla.
NOMBRES_PUBLICOS_TEMPORADA = {
    "invierno": "invierno",
    "verano": "verano",
    "agosto": "agosto",
}

CONDICIONES_CONOCIDAS = {
    "a_demanda",
    "solo_viernes_lectivo",
    "solo_si_viajeros_desde_cordoba",
}

CAMPOS_LINEA_OBLIGATORIOS = {"nombre", "temporadas", "dias", "horarios"}
CAMPOS_LINEA_PERMITIDOS = CAMPOS_LINEA_OBLIGATORIOS | {
    "telefono_demanda",
    "avisos",
    "no_circula",
    "pendientes",
    "nombre_corto",
}
# Campos permitidos de paradas.yaml y observaciones.yaml: todo lo demás es un
# error (suele ser un nombre con coma sin comillas dentro de `{ ... }`).
CAMPOS_PARADAS_TOPE = {"localidades", "paradas", "pendientes", "no_vendibles"}
CAMPOS_LOCALIDAD = {"nombre", "alias", "pendiente", "ver", "minutos", "aviso"}
CAMPOS_PARADA = {"nombre", "localidad"}
CAMPOS_OBSERVACION = {"letra", "tipo", "ambitos", "texto"}
# Título de fila de una lista interactiva de WhatsApp.
MAX_TITULO_LINEA = 24
LINEA_ID_RE = re.compile(r"^[a-z0-9-]+$")

# ── calendario.yaml ──────────────────────────────────────────────────────────────────
# Fechas con año real (a diferencia de las temporadas de línea, que no lo
# llevan): parser distinto y sin relación con `_parse_temporada_rango` /
# `_DIAS_DEL_ANIO` (que son año-independientes y se reutilizan cada año).
FECHA_RE = re.compile(r"^(\d{2})/(\d{2})/(\d{4})$")
RANGO_FECHA_RE = re.compile(r"^(\d{2})/(\d{2})/(\d{4})\s*-\s*(\d{2})/(\d{2})/(\d{4})$")

CAMPOS_CALENDARIO_OBLIGATORIOS = {"vigencia", "festivos", "curso"}
CAMPOS_CALENDARIO_PERMITIDOS = CAMPOS_CALENDARIO_OBLIGATORIOS | {
    "pendientes",
    "sin_servicio_todas_las_lineas",
    "festivos_locales",
}
DIA_MES_RE = re.compile(r"^(\d{2})/(\d{2})$")
CAMPOS_CURSO_OBLIGATORIOS = {"inicio_clases", "fin_clases", "vacaciones", "no_lectivos"}

_MESES = {
    "enero": 1,
    "febrero": 2,
    "marzo": 3,
    "abril": 4,
    "mayo": 5,
    "junio": 6,
    "julio": 7,
    "agosto": 8,
    "septiembre": 9,
    "octubre": 10,
    "noviembre": 11,
    "diciembre": 12,
}

# Los 366 días del año (mes, día), usando un año bisiesto como calendario de
# referencia. Sirve para comprobar que las temporadas cubren el año entero,
# incluido el 29 de febrero, sin años reales (D-a).
_DIAS_DEL_ANIO: list[tuple[int, int]] = [
    (mes, dia) for mes in range(1, 13) for dia in range(1, calendar.monthrange(2024, mes)[1] + 1)
]
_INDICE_DIA = {md: i for i, md in enumerate(_DIAS_DEL_ANIO)}

# Artículos y preposiciones de enlace que se descartan al
# normalizar (villanueva duque = Villanueva del Duque).
_PALABRAS_VACIAS_NORMALIZAR = frozenset({"el", "la", "los", "las", "de", "del"})


def normalizar(texto: str) -> str:
    """Normalización única de nombres de localidad/parada y sus alias:
    `core.text.normalize` (minúsculas, sin tildes,
    sin puntuación, colapsada a espacio) y sin artículos/preposiciones de
    enlace. La comparten el validador (aquí) y `packs.bus.matcher`; ningún
    otro módulo vuelve a normalizar un nombre por su cuenta."""
    return " ".join(p for p in normalize(texto).split() if p not in _PALABRAS_VACIAS_NORMALIZAR)


@dataclass
class Modelo:
    localidades: dict[str, Localidad]
    paradas: dict[str, Parada]
    observaciones: dict[str, Observacion]
    lineas: dict[str, Linea]
    pendientes: tuple[str, ...] = ()  # pendientes declarados en paradas.yaml
    # Pares de localidades entre las que la empresa no vende billetes, en
    # ninguno de los dos sentidos (P12b), declarados en paradas.yaml.
    no_vendibles: frozenset[frozenset[str]] = frozenset()
    calendario: Calendario | None = None  # None solo si validar() no llegó a
    # construirlo (errores); formato.validar() siempre lo rellena si no hay
    # errores. test_diff.py construye Modelo(...) a mano sin pasar por
    # validar() y depende de este valor por defecto.


@dataclass
class Resultado:
    modelo: Modelo | None
    errores: list[str]
    avisos: list[str]


def _cargar_yaml(path: Path, errores: list[str]) -> dict[str, Any] | None:
    try:
        texto = path.read_text(encoding="utf-8")
    except OSError as exc:
        errores.append(f"{path}: no se puede leer el fichero ({exc})")
        return None
    try:
        datos = yaml.safe_load(texto)
    except yaml.YAMLError as exc:
        errores.append(f"{path}: YAML mal formado ({exc})")
        return None
    if datos is None:
        datos = {}
    if not isinstance(datos, dict):
        errores.append(f"{path}: YAML mal formado (se esperaba un mapa en la raíz)")
        return None
    return datos


def _parse_temporada_rango(rango: str) -> list[int] | None:
    """Devuelve la lista de índices (en _DIAS_DEL_ANIO) que cubre el rango, o
    None si el formato es inválido."""
    rango = rango.strip()
    if rango.lower() == "todo el año" or rango.lower() == "todo el ano":
        return list(range(len(_DIAS_DEL_ANIO)))
    m = re.match(r"^(\d{2})/(\d{2})\s*-\s*(\d{2})/(\d{2})$", rango)
    if not m:
        return None
    d1, m1, d2, m2 = (int(x) for x in m.groups())
    try:
        i1 = _INDICE_DIA[(m1, d1)]
        i2 = _INDICE_DIA[(m2, d2)]
    except KeyError:
        return None
    if i1 <= i2:
        return list(range(i1, i2 + 1))
    return list(range(i1, len(_DIAS_DEL_ANIO))) + list(range(0, i2 + 1))


def temporada_de_linea(linea: Linea, mes: int, dia: int) -> Temporada | None:
    """Temporada de `linea` vigente para ese día/mes.

    Único punto que vuelve a interpretar un rango de temporada de línea fuera
    de la validación: reutiliza `_parse_temporada_rango`, el mismo parser
    año-independiente que usa `_validar_linea`.
    `packs.bus.calendario.temporada_de` delega aquí; nadie más vuelve a
    parsear esto."""
    try:
        indice = _INDICE_DIA[(mes, dia)]
    except KeyError:
        return None
    for temporada in linea.temporadas:
        indices = _parse_temporada_rango(temporada.rango)
        if indices is not None and indice in indices:
            return temporada
    return None


def _parse_fecha_calendario(txt: str) -> date | None:
    """Fecha con año real 'DD/MM/AAAA' (calendario.yaml). Distinto del rango
    año-independiente 'DD/MM - DD/MM' de las temporadas de línea."""
    m = FECHA_RE.match(txt.strip())
    if not m:
        return None
    d, mo, y = (int(x) for x in m.groups())
    try:
        return date(y, mo, d)
    except ValueError:
        return None


def _parse_rango_fechas_calendario(txt: str) -> tuple[date, date] | None:
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


def _claves_desconocidas(
    campos: dict[str, Any],
    permitidos: set[str],
    etiqueta: str,
    path: Path,
    errores: list[str],
    *,
    ignorar: tuple[str, ...] | set[str] = (),
) -> None:
    """Un error por cada clave de `campos` que no está en `permitidos`."""
    desconocidas = [k for k in campos if k not in permitidos and k not in ignorar]
    for k in sorted(desconocidas, key=str):
        msg = f"{path}: {etiqueta}: campo desconocido '{k}'"
        if campos[k] is None and "nombre" in campos:
            msg += " (¿un nombre con coma sin comillas?)"
        errores.append(msg)


def _validar_localidades_paradas(
    datos_paradas: dict[str, Any], path: Path, errores: list[str], avisos: list[str]
) -> tuple[dict[str, Localidad], dict[str, Parada]]:
    localidades: dict[str, Localidad] = {}
    paradas: dict[str, Parada] = {}

    _claves_desconocidas(
        datos_paradas,
        CAMPOS_PARADAS_TOPE,
        "paradas.yaml",
        path,
        errores,
        ignorar={"zonas"},
    )
    if "zonas" in datos_paradas:
        errores.append(f"{path}: campo obsoleto 'zonas' (P18: los pueblos se agrupan por línea)")

    localidades_raw = datos_paradas.get("localidades")
    if not isinstance(localidades_raw, dict):
        errores.append(f"{path}: falta el campo obligatorio 'localidades' (mapa)")
        localidades_raw = {}
    for lid, campos in localidades_raw.items():
        if isinstance(campos, dict):
            _claves_desconocidas(
                campos,
                CAMPOS_LOCALIDAD,
                f"localidad '{lid}'",
                path,
                errores,
                ignorar={"zona"},
            )
        if not isinstance(campos, dict) or "nombre" not in campos:
            errores.append(f"{path}: localidad '{lid}' sin 'nombre'")
            continue
        if "zona" in campos:
            errores.append(
                f"{path}: localidad '{lid}': campo obsoleto 'zona' (P18: los "
                "pueblos se agrupan por línea)"
            )

        nombre_norm = normalizar(str(campos["nombre"]))
        alias_raw = campos.get("alias", []) or []
        if not isinstance(alias_raw, list) or any(not isinstance(a, str) for a in alias_raw):
            errores.append(
                f"{path}: localidad '{lid}': 'alias' debe ser una lista de cadenas ({alias_raw!r})"
            )
            alias_raw = []
        alias_normalizados_vistos: set[str] = set()
        for a in alias_raw:
            a_norm = normalizar(a)
            if a_norm == "":
                errores.append(
                    f"{path}: localidad '{lid}': el alias '{a}' normaliza a una cadena vacía"
                )
                continue
            if a_norm in alias_normalizados_vistos:
                errores.append(
                    f"{path}: localidad '{lid}': el alias '{a}' está "
                    "repetido (normaliza igual que otro alias de la misma "
                    "localidad)"
                )
                continue
            alias_normalizados_vistos.add(a_norm)
            if a_norm == nombre_norm:
                errores.append(
                    f"{path}: localidad '{lid}': el alias '{a}' coincide con "
                    "el propio nombre de la localidad"
                )

        alias = tuple(str(a) for a in alias_raw)

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
            elif (
                isinstance(minutos, bool) or not isinstance(minutos, int) or not 1 <= minutos <= 60
            ):
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
        if ver is not None:
            ver = str(ver)
        if aviso is not None:
            aviso = str(aviso)
        localidades[lid] = Localidad(
            id=lid,
            nombre=str(campos["nombre"]),
            alias=alias,
            pendiente=pendiente,
            ver=ver,
            minutos=minutos,
            aviso=aviso,
        )

    # Dos localidades cuyo nombre normalizado coincide es una ambigüedad no
    # declarada (a diferencia de un alias compartido, que se avisa más abajo):
    # error, no aviso.
    nombre_a_lids: dict[str, list[str]] = {}
    for lid, loc in localidades.items():
        nombre_a_lids.setdefault(normalizar(loc.nombre), []).append(lid)
    for nombre_norm, lids in nombre_a_lids.items():
        if len(lids) > 1:
            errores.append(
                f"{path}: localidades {sorted(lids)} tienen el mismo nombre "
                f"normalizado ('{nombre_norm}'), sin declarar cómo distinguirlas"
            )

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
            _claves_desconocidas(campos, CAMPOS_PARADA, f"parada '{codigo}'", path, errores)
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

    # Una parada cuyo nombre normalizado coincide con el de OTRA localidad
    # (no la suya) confundiría al matcher: error, no aviso.
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

    # Ambigüedades declaradas (aviso, no error): un nombre o alias compartido
    # por varias localidades, o un alias que coincide con el nombre de otra
    # (caso real: 'villafranca').
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

    return localidades, paradas


def _validar_pendientes_paradas(
    datos_paradas: dict[str, Any], path: Path, errores: list[str], avisos: list[str]
) -> tuple[str, ...]:
    """Lee el campo opcional `pendientes:` de paradas.yaml:
    preguntas abiertas que no están ligadas a ninguna línea concreta (p.ej.
    P32, posición de una aldea en la ruta)."""
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


def _validar_localidades_pendientes(
    path: Path,
    localidades: dict[str, Localidad],
    paradas: dict[str, Parada],
    observaciones: dict[str, Observacion],
    pendientes_paradas: tuple[str, ...],
    errores: list[str],
    avisos: list[str],
) -> None:
    """Localidades pendientes (P15/P32): aldeas sin hora de paso propia.
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


def _validar_no_vendibles(
    datos_paradas: dict[str, Any],
    path: Path,
    localidades: dict[str, Localidad],
    errores: list[str],
) -> frozenset[frozenset[str]]:
    """Lee el campo opcional `no_vendibles:` de paradas.yaml (P12b): lista de
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


def _validar_calendario(
    directorio: Path,
    errores: list[str],
    avisos: list[str],
    localidades: dict[str, Localidad],
) -> Calendario | None:
    """Valida `calendario.yaml`: festivos y periodo
    escolar, con fechas de año real. Nunca adivina: fecha inválida, rango
    invertido, festivo duplicado o fuera de vigencia, campo desconocido o
    ausente, e inicio de curso posterior al fin son errores concretos."""
    path = directorio / "calendario.yaml"
    datos = _cargar_yaml(path, errores)
    if datos is None:
        return None

    campos_desconocidos = set(datos.keys()) - CAMPOS_CALENDARIO_PERMITIDOS
    if campos_desconocidos:
        errores.append(f"{path}: campo(s) desconocido(s): {sorted(campos_desconocidos)}")
    campos_ausentes = CAMPOS_CALENDARIO_OBLIGATORIOS - set(datos.keys())
    if campos_ausentes:
        errores.append(f"{path}: falta(n) campo(s) obligatorio(s): {sorted(campos_ausentes)}")
        return None

    vigencia_raw = datos["vigencia"]
    rango_vigencia = _parse_rango_fechas_calendario(str(vigencia_raw))
    if rango_vigencia is None:
        errores.append(
            f"{path}: 'vigencia' con rango inválido '{vigencia_raw}' (se "
            "esperaba 'DD/MM/AAAA - DD/MM/AAAA')"
        )
        return None
    vigencia_inicio, vigencia_fin = rango_vigencia
    if vigencia_fin < vigencia_inicio:
        errores.append(
            f"{path}: 'vigencia' con fecha de fin anterior a la de inicio ('{vigencia_raw}')"
        )
        return None

    def _en_vigencia(f: date, contexto: str) -> None:
        if f < vigencia_inicio or f > vigencia_fin:
            errores.append(
                f"{path}: {contexto} ({f.strftime('%d/%m/%Y')}) fuera de la "
                f"vigencia del calendario ('{vigencia_raw}')"
            )

    festivos_raw = datos["festivos"]
    festivos: dict[date, str] = {}
    if not isinstance(festivos_raw, dict) or not festivos_raw:
        errores.append(f"{path}: 'festivos' debe ser un mapa no vacío")
        festivos_raw = {}
    for fecha_txt, nombre in festivos_raw.items():
        fecha = _parse_fecha_calendario(str(fecha_txt))
        if fecha is None:
            errores.append(
                f"{path}: festivo con fecha inválida '{fecha_txt}' (se esperaba 'DD/MM/AAAA')"
            )
            continue
        if fecha in festivos:
            errores.append(f"{path}: festivo duplicado '{fecha_txt}'")
            continue
        _en_vigencia(fecha, f"festivo '{nombre}'")
        festivos[fecha] = str(nombre)

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

    inicio_clases: date | None = None
    if "inicio_clases" in curso_raw:
        inicio_clases = _parse_fecha_calendario(str(curso_raw["inicio_clases"]))
        if inicio_clases is None:
            errores.append(
                f"{path}: 'curso.inicio_clases' con fecha inválida '{curso_raw['inicio_clases']}'"
            )
        else:
            _en_vigencia(inicio_clases, "'curso.inicio_clases'")

    fin_clases: date | None = None
    if "fin_clases" in curso_raw:
        fin_clases = _parse_fecha_calendario(str(curso_raw["fin_clases"]))
        if fin_clases is None:
            errores.append(
                f"{path}: 'curso.fin_clases' con fecha inválida '{curso_raw['fin_clases']}'"
            )
        else:
            _en_vigencia(fin_clases, "'curso.fin_clases'")

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
        rango = _parse_rango_fechas_calendario(str(rango_txt))
        if rango is None:
            errores.append(f"{path}: 'curso.vacaciones' con rango inválido '{rango_txt}'")
            continue
        f1, f2 = rango
        if f2 < f1:
            errores.append(f"{path}: 'curso.vacaciones' con rango invertido '{rango_txt}'")
            continue
        _en_vigencia(f1, f"'curso.vacaciones' ({rango_txt}), inicio")
        _en_vigencia(f2, f"'curso.vacaciones' ({rango_txt}), fin")
        vacaciones.append((f1, f2))

    no_lectivos_raw = curso_raw.get("no_lectivos", [])
    no_lectivos: list[date] = []
    if not isinstance(no_lectivos_raw, list):
        errores.append(f"{path}: 'curso.no_lectivos' debe ser una lista")
        no_lectivos_raw = []
    for fecha_txt in no_lectivos_raw:
        fecha = _parse_fecha_calendario(str(fecha_txt))
        if fecha is None:
            errores.append(f"{path}: 'curso.no_lectivos' con fecha inválida '{fecha_txt}'")
            continue
        _en_vigencia(fecha, "'curso.no_lectivos'")
        no_lectivos.append(fecha)

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
            fecha = _parse_fecha_calendario(str(fecha_txt))
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
            _en_vigencia(fecha, f"festivo local '{nombre}' de '{loc_id}'")
            if fecha in festivos:
                errores.append(
                    f"{path}: 'festivos_locales.{loc_id}': la fecha "
                    f"'{fecha_txt}' ya está en 'festivos' ('{festivos[fecha]}')"
                )
                continue
            de_la_localidad[fecha] = str(nombre)
        festivos_locales[loc_id] = de_la_localidad

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
        if (mes_n, dia_n) not in _INDICE_DIA:
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

    pendientes_raw = datos.get("pendientes", []) or []
    pendientes: list[str] = []
    if not isinstance(pendientes_raw, list):
        errores.append(f"{path}: 'pendientes' debe ser una lista")
    else:
        for p in pendientes_raw:
            p = str(p)
            if not PENDIENTE_RE.match(p):
                errores.append(f"{path}: pendiente inválido '{p}' (debe cumplir P\\d{{2}})")
                continue
            pendientes.append(p)
            avisos.append(f"{path}: pendiente {p}")

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


def _validar_observaciones(
    datos: dict[str, Any], path: Path, errores: list[str]
) -> dict[str, Observacion]:
    observaciones: dict[str, Observacion] = {}
    for oid, campos in datos.items():
        if isinstance(campos, dict):
            _claves_desconocidas(campos, CAMPOS_OBSERVACION, f"observación '{oid}'", path, errores)
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


def _obs_por_letra(observaciones: dict[str, Observacion]) -> dict[str, Observacion]:
    return {o.letra: o for o in observaciones.values() if o.letra}


def texto_observacion(obs: Observacion, linea: Linea) -> str:
    """Texto literal que verá el cliente para `obs`, con `{telefono}`
    sustituido por el `telefono_demanda` de `linea` cuando lo hay. No hace
    nada si el texto no tiene el marcador o la línea no define teléfono."""
    if "{telefono}" in obs.texto and linea.telefono_demanda:
        return obs.texto.replace("{telefono}", linea.telefono_demanda)
    return obs.texto


@dataclass
class _FilaTabla:
    valores: list[str]
    obs_viaje: list[str]
    pendientes: list[str]
    numero: int  # fila dentro de la tabla (1-based, sin cabecera ni comentarios)
    # ids escritos como `bus:<id>` tras el `|` (sin validar; puede haber 0, 1 o más)
    bus: list[str] = field(default_factory=list)


def _parse_tabla(texto: str) -> tuple[list[str] | None, list[_FilaTabla]]:
    """Devuelve (cabecera, filas). cabecera es None si no hay ninguna línea útil."""
    lineas = [
        line for line in texto.splitlines() if line.strip() and not line.strip().startswith("#")
    ]
    if not lineas:
        return None, []
    cabecera = lineas[0].split()
    filas: list[_FilaTabla] = []
    for i, linea in enumerate(lineas[1:], start=1):
        if "|" in linea:
            izquierda, derecha = linea.split("|", 1)
            valores = izquierda.split()
            resto = derecha.split()
        else:
            valores = linea.split()
            resto = []
        buses = [tok[len("bus:") :] for tok in resto if tok.startswith("bus:")]
        resto = [tok for tok in resto if not tok.startswith("bus:")]
        obs_viaje = [tok for tok in resto if not PENDIENTE_RE.match(tok)]
        pendientes = [tok for tok in resto if PENDIENTE_RE.match(tok)]
        filas.append(
            _FilaTabla(
                valores=valores,
                obs_viaje=obs_viaje,
                pendientes=pendientes,
                numero=i,
                bus=buses,
            )
        )
    return cabecera, filas


def _hora_a_minutos(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


@dataclass
class _InfoViaje:
    """Datos auxiliares de un viaje para las comprobaciones entre líneas
    (grupos `bus:` y aviso heurístico). No forma parte del modelo publicado."""

    viaje: Viaje
    ruta: str  # fichero de la línea
    etiqueta: str  # "fichero [temporada, dias, tabla], fila N"
    indices: frozenset[int]  # días del año (índices de _DIAS_DEL_ANIO)
    clases: frozenset[str]  # clases de día de la tabla


def _validar_linea(
    lid: str,
    datos: dict[str, Any],
    path: Path,
    paradas: dict[str, Parada],
    observaciones: dict[str, Observacion],
    errores: list[str],
    avisos: list[str],
    infos_viaje: list[_InfoViaje] | None = None,
) -> Linea | None:
    campos_desconocidos = set(datos.keys()) - CAMPOS_LINEA_PERMITIDOS
    if campos_desconocidos:
        errores.append(f"{path}: campo(s) desconocido(s): {sorted(campos_desconocidos)}")
    campos_ausentes = CAMPOS_LINEA_OBLIGATORIOS - set(datos.keys())
    if campos_ausentes:
        errores.append(f"{path}: falta(n) campo(s) obligatorio(s): {sorted(campos_ausentes)}")
        return None

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
    telefono_demanda = datos.get("telefono_demanda")
    avisos_linea = datos.get("avisos", []) or []
    no_circula = datos.get("no_circula", []) or []
    pendientes_linea = datos.get("pendientes", []) or []

    for p in pendientes_linea:
        if not PENDIENTE_RE.match(p):
            errores.append(f"{path}: pendiente inválido '{p}' (debe cumplir P\\d{{2}})")

    obs_por_letra = _obs_por_letra(observaciones)

    # avisos de línea deben ser observaciones de ámbito línea, existentes
    for oid in avisos_linea:
        obs = observaciones.get(oid)
        if obs is None:
            errores.append(f"{path}: aviso de línea '{oid}' sin definir en observaciones.yaml")
        elif "linea" not in obs.ambitos:
            errores.append(
                f"{path}: observación '{oid}' usada en ámbito 'linea' pero no lo permite"
            )

    # ── temporadas ───────────────────────────────────────────────────────
    temporadas_raw = datos["temporadas"]
    if not isinstance(temporadas_raw, dict) or not temporadas_raw:
        errores.append(f"{path}: 'temporadas' debe ser un mapa no vacío")
        temporadas_raw = {}

    temporadas: list[Temporada] = []
    indices_temporada: dict[str, frozenset[int]] = {}
    cobertura = [0] * len(_DIAS_DEL_ANIO)
    for nombre_temp, rango in temporadas_raw.items():
        indices = _parse_temporada_rango(str(rango))
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

    nombres_temporada = {t.nombre for t in temporadas}

    # ── dias (estado de cada clase de día, por temporada) ───────────────
    dias_raw = datos["dias"]
    dias_estado: dict[str, dict[str, str]] = {}
    if not isinstance(dias_raw, dict):
        errores.append(f"{path}: 'dias' debe ser un mapa temporada -> claves de día")
        dias_raw = {}

    for nombre_temp in nombres_temporada:
        declaracion = dias_raw.get(nombre_temp)
        estado_por_clase: dict[str, str] = {}
        if not isinstance(declaracion, dict):
            errores.append(f"{path}: la temporada '{nombre_temp}' no declara 'dias'")
            dias_estado[nombre_temp] = estado_por_clase
            continue
        cobertura_clases: dict[str, int] = {c: 0 for c in DIAS_INDIVIDUALES}
        for clave, estado in declaracion.items():
            if clave not in GRUPOS_DIA:
                errores.append(
                    f"{path}: temporada '{nombre_temp}': clave de día desconocida '{clave}'"
                )
                continue
            if estado not in ESTADOS_DIA:
                errores.append(
                    f"{path}: temporada '{nombre_temp}', día '{clave}': estado "
                    f"desconocido '{estado}'"
                )
                continue
            # En orden de semana: un frozenset no da un orden estable entre ejecuciones.
            for clase in sorted(GRUPOS_DIA[clave], key=DIAS_INDIVIDUALES.index):
                cobertura_clases[clase] += 1
                estado_por_clase[clase] = estado
                if estado == "sin_datos":
                    avisos.append(
                        f"{path}: {lid}, temporada '{nombre_temp}', '{clase}': "
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
        dias_estado[nombre_temp] = estado_por_clase

    # ── horarios (tablas) ────────────────────────────────────────────────
    horarios_raw = datos["horarios"]
    if not isinstance(horarios_raw, list) or not horarios_raw:
        errores.append(f"{path}: 'horarios' debe ser una lista no vacía de tablas")
        horarios_raw = []

    viajes: list[Viaje] = []
    tablas: list[Tabla] = []
    clases_cubiertas: dict[str, set[str]] = {t: set() for t in nombres_temporada}
    usa_a_demanda = False

    # Varias tablas de la misma línea pueden compartir temporada+dias (p.ej.
    # ida y vuelta ambas anual/sábado): sin más información en el esquema
    # (el formato no declara un campo de sentido por tabla), se numeran
    # "tabla N de M" para que los avisos/errores de cada una sean
    # distinguibles.
    claves_tabla = [
        (entrada["temporada"], entrada["dias"])
        for entrada in horarios_raw
        if isinstance(entrada, dict) and {"temporada", "dias", "tabla"} <= set(entrada.keys())
    ]
    conteo_claves: dict[tuple[Any, Any], int] = {}
    for clave in claves_tabla:
        conteo_claves[clave] = conteo_claves.get(clave, 0) + 1
    indice_clave: dict[tuple[Any, Any], int] = {}

    for entrada in horarios_raw:
        if not isinstance(entrada, dict) or not {"temporada", "dias", "tabla"} <= set(
            entrada.keys()
        ):
            errores.append(
                f"{path}: entrada de 'horarios' incompleta (faltan temporada/dias/tabla)"
            )
            continue
        temporada_e = entrada["temporada"]
        dias_e = entrada["dias"]
        tabla_txt = entrada["tabla"]
        clave = (temporada_e, dias_e)
        if conteo_claves.get(clave, 0) > 1:
            indice_clave[clave] = indice_clave.get(clave, 0) + 1
            etiqueta_tabla = (
                f"{path} [temporada={temporada_e}, dias={dias_e}, "
                f"tabla {indice_clave[clave]} de {conteo_claves[clave]}]"
            )
        else:
            etiqueta_tabla = f"{path} [temporada={temporada_e}, dias={dias_e}]"

        if temporada_e not in nombres_temporada:
            errores.append(f"{etiqueta_tabla}: referencia una temporada sin declarar")
            continue
        if dias_e not in GRUPOS_DIA:
            errores.append(f"{etiqueta_tabla}: clave de día desconocida '{dias_e}'")
            continue

        cabecera, filas = _parse_tabla(tabla_txt)
        if cabecera is None:
            errores.append(f"{etiqueta_tabla}: tabla vacía")
            continue
        if len(cabecera) < 2:
            errores.append(f"{etiqueta_tabla}: la cabecera debe tener al menos 2 paradas")
        if len(cabecera) != len(set(cabecera)):
            errores.append(f"{etiqueta_tabla}: paradas repetidas en la cabecera {cabecera}")
        for codigo in cabecera:
            if codigo not in paradas:
                errores.append(f"{etiqueta_tabla}: código de parada sin definir '{codigo}'")

        tabla_actual = Tabla(
            linea=lid,
            temporada=temporada_e,
            dias=dias_e,
            paradas=tuple(cabecera),
            posicion=len(tablas),
        )
        tablas.append(tabla_actual)

        for fila in filas:
            if len(fila.valores) != len(cabecera):
                errores.append(
                    f"{etiqueta_tabla}, fila {fila.numero}: "
                    f"{len(fila.valores)} valores, se esperaban "
                    f"{len(cabecera)} (uno por parada)"
                )
                continue

            pasos: list[Paso] = []
            # (llegada, salida) en minutos de cada celda con hora válida
            horas_validas: list[tuple[int, int]] = []
            fila_valida = True
            indices_con_valor = [i for i, v in enumerate(fila.valores) if v != "-"]
            primero = indices_con_valor[0] if indices_con_valor else -1
            ultimo = indices_con_valor[-1] if indices_con_valor else -1
            for indice, (codigo, valor) in enumerate(zip(cabecera, fila.valores, strict=True)):
                if valor == "-":
                    continue
                m = CELDA_HORA_RE.match(valor)
                if not m:
                    errores.append(
                        f"{etiqueta_tabla}, fila {fila.numero}: valor inválido "
                        f"'{valor}' en '{codigo}'"
                    )
                    fila_valida = False
                    continue
                llegada_txt = m.group(1)
                salida_txt = m.group(2) or llegada_txt
                letras = m.group(3)
                llegada_min = _hora_a_minutos(llegada_txt)
                salida_min = _hora_a_minutos(salida_txt)
                if m.group(2) is not None:
                    if indice in (primero, ultimo):
                        errores.append(
                            f"{etiqueta_tabla}, fila {fila.numero}: llegada y "
                            "salida solo en una parada intermedia del viaje "
                            f"('{codigo}')"
                        )
                        fila_valida = False
                    elif salida_min == llegada_min:
                        errores.append(
                            f"{etiqueta_tabla}, fila {fila.numero}: misma hora "
                            f"dos veces en '{codigo}'; escribe una sola"
                        )
                        fila_valida = False
                    elif salida_min < llegada_min:
                        errores.append(
                            f"{etiqueta_tabla}, fila {fila.numero}: la llegada "
                            f"debe ser anterior a la salida en '{codigo}' "
                            f"({llegada_txt}>{salida_txt})"
                        )
                        fila_valida = False
                if horas_validas and llegada_min < horas_validas[-1][1]:
                    errores.append(
                        f"{etiqueta_tabla}, fila {fila.numero}: las horas "
                        f"retroceden en '{codigo}' ({llegada_txt})"
                    )
                horas_validas.append((llegada_min, salida_min))

                obs_parada: list[str] = []
                for letra in letras:
                    obs = obs_por_letra.get(letra)
                    if obs is None:
                        errores.append(
                            f"{etiqueta_tabla}, fila {fila.numero}: letra de "
                            f"observación sin definir '{letra}' en '{codigo}'"
                        )
                        continue
                    if "parada" not in obs.ambitos:
                        errores.append(
                            f"{etiqueta_tabla}, fila {fila.numero}: observación "
                            f"'{obs.id}' usada en ámbito 'parada' pero no lo permite"
                        )
                        continue
                    if obs.tipo == "condicion" and obs.id not in CONDICIONES_CONOCIDAS:
                        errores.append(
                            f"{etiqueta_tabla}, fila {fila.numero}: condición "
                            f"'{obs.id}' que el motor no sabe aplicar"
                        )
                        continue
                    if obs.id == "a_demanda":
                        usa_a_demanda = True
                    obs_parada.append(obs.id)
                pasos.append(
                    Paso(
                        parada=codigo,
                        llegada=llegada_txt,
                        salida=salida_txt,
                        observaciones=tuple(obs_parada),
                    )
                )

            if fila_valida and len(horas_validas) < 2:
                errores.append(
                    f"{etiqueta_tabla}, fila {fila.numero}: el viaje tiene menos de 2 horas"
                )

            obs_viaje_ids: list[str] = []
            for tok in fila.obs_viaje:
                obs = observaciones.get(tok)
                if obs is None:
                    errores.append(
                        f"{etiqueta_tabla}, fila {fila.numero}: observación de "
                        f"viaje sin definir '{tok}'"
                    )
                    continue
                if "viaje" not in obs.ambitos:
                    errores.append(
                        f"{etiqueta_tabla}, fila {fila.numero}: observación "
                        f"'{tok}' usada en ámbito 'viaje' pero no lo permite"
                    )
                    continue
                if obs.tipo == "condicion" and obs.id not in CONDICIONES_CONOCIDAS:
                    errores.append(
                        f"{etiqueta_tabla}, fila {fila.numero}: condición '{tok}' "
                        "que el motor no sabe aplicar"
                    )
                    continue
                obs_viaje_ids.append(obs.id)

            pendientes_fila: list[str] = []
            for tok in fila.pendientes:
                if not PENDIENTE_RE.match(tok):
                    errores.append(
                        f"{etiqueta_tabla}, fila {fila.numero}: pendiente inválido '{tok}'"
                    )
                    continue
                pendientes_fila.append(tok)
                avisos.append(f"{etiqueta_tabla}, fila {fila.numero}: pendiente {tok}")

            bus_id: str | None = None
            if len(fila.bus) > 1:
                errores.append(
                    f"{etiqueta_tabla}, fila {fila.numero}: más de un 'bus:' en "
                    f"el mismo viaje ({['bus:' + b for b in fila.bus]})"
                )
            for candidato in fila.bus[:1]:
                if BUS_ID_RE.match(candidato):
                    bus_id = candidato
                else:
                    errores.append(
                        f"{etiqueta_tabla}, fila {fila.numero}: identificador "
                        f"de autobús inválido 'bus:{candidato}' (solo minúsculas, "
                        "cifras y guiones)"
                    )

            viaje_nuevo = Viaje(
                linea=lid,
                temporada=temporada_e,
                dias=dias_e,
                tabla=tabla_actual,
                observaciones=tuple(obs_viaje_ids),
                pendientes=tuple(pendientes_fila),
                pasos=tuple(pasos),
                bus=bus_id,
            )
            viajes.append(viaje_nuevo)
            if infos_viaje is not None:
                infos_viaje.append(
                    _InfoViaje(
                        viaje=viaje_nuevo,
                        ruta=str(path),
                        etiqueta=f"{etiqueta_tabla}, fila {fila.numero}",
                        indices=indices_temporada.get(temporada_e, frozenset()),
                        clases=GRUPOS_DIA[dias_e],
                    )
                )

        clases_cubiertas.setdefault(temporada_e, set()).update(GRUPOS_DIA[dias_e])

    # Dos tablas con la misma temporada, días y extremos de cabecera serían
    # indistinguibles para el diff y para la vista de revisión: a diferencia de
    # "tabla N de M" (que solo numera avisos), esto es
    # un error porque probablemente son la misma tabla duplicada por error.
    firmas_tabla: dict[tuple[str, str, str, str], list[Tabla]] = {}
    for t in tablas:
        if len(t.paradas) < 2:
            continue
        firma = (t.temporada, t.dias, t.paradas[0], t.paradas[-1])
        firmas_tabla.setdefault(firma, []).append(t)
    for (temporada_f, dias_f, primera_f, ultima_f), lista in firmas_tabla.items():
        if len(lista) > 1:
            errores.append(
                f"{path}: {len(lista)} tablas con temporada '{temporada_f}', "
                f"días '{dias_f}', de '{primera_f}' a '{ultima_f}' (deben "
                "distinguirse por sus extremos; si no, son la misma tabla "
                "duplicada)"
            )

    # clase con estado 'horario' que ninguna tabla cubre
    for nombre_temp, estado_por_clase in dias_estado.items():
        for clase, estado in estado_por_clase.items():
            if estado == "horario" and clase not in clases_cubiertas.get(nombre_temp, set()):
                errores.append(
                    f"{path}: temporada '{nombre_temp}', clase '{clase}': "
                    "estado 'horario' sin ninguna tabla que la cubra"
                )
        # avisar de pendientes de línea (una sola vez, ya se listan en pendientes_linea)

    if usa_a_demanda and not telefono_demanda:
        errores.append(f"{path}: se usa 'a_demanda' pero la línea no define 'telefono_demanda'")

    for p in pendientes_linea:
        if PENDIENTE_RE.match(p):
            avisos.append(f"{path}: {lid}: pendiente de línea {p}")

    return Linea(
        id=lid,
        nombre=str(nombre),
        telefono_demanda=telefono_demanda,
        avisos=tuple(avisos_linea),
        no_circula=tuple(no_circula),
        temporadas=tuple(temporadas),
        dias=dias_estado,
        pendientes=tuple(pendientes_linea),
        viajes=tuple(viajes),
        tablas=tuple(tablas),
        nombre_corto=nombre_corto,
    )


def _solapan(a: _InfoViaje, b: _InfoViaje) -> bool:
    """True si los dos viajes pueden circular el mismo día del año: sus
    temporadas comparten alguna fecha Y sus clases de día comparten alguna."""
    return not a.indices.isdisjoint(b.indices) and not a.clases.isdisjoint(b.clases)


def _texto_hora_paso(paso: Paso) -> str:
    if paso.llegada == paso.salida:
        return paso.llegada
    return f"{paso.llegada}>{paso.salida}"


def _horas_distintas_en_comunes(
    a: Viaje, b: Viaje, codigos: list[str]
) -> list[tuple[str, Paso, Paso]]:
    """Paradas comunes de `codigos` (en orden) cuyas horas no cuadran entre los
    dos viajes: la llegada siempre, y la salida solo si la parada no es la
    última de ninguno de los dos viajes (un viaje que termina ahí no tiene
    salida que comparar)."""
    idx_a = {p.parada: i for i, p in enumerate(a.pasos)}
    idx_b = {p.parada: i for i, p in enumerate(b.pasos)}
    distintas: list[tuple[str, Paso, Paso]] = []
    for codigo in codigos:
        ia, ib = idx_a[codigo], idx_b[codigo]
        pa, pb = a.pasos[ia], b.pasos[ib]
        ultima_alguno = ia == len(a.pasos) - 1 or ib == len(b.pasos) - 1
        if pa.llegada != pb.llegada or (not ultima_alguno and pa.salida != pb.salida):
            distintas.append((codigo, pa, pb))
    return distintas


def _validar_buses(
    infos: list[_InfoViaje],
    paradas: dict[str, Parada],
    localidades: dict[str, Localidad],
    errores: list[str],
) -> None:
    """Grupos `bus:<id>` declarados: todo lo declarado tiene
    que cuadrar; si no, error concreto. Solo compara entre sí los miembros que
    circulan algún mismo día (el mismo `bus:` puede repartirse entre viajes
    de días distintos, p.ej. Badajoz lunes-jueves y viernes)."""
    grupos: dict[str, list[_InfoViaje]] = {}
    for info in infos:
        if info.viaje.bus is not None:
            grupos.setdefault(info.viaje.bus, []).append(info)

    def loc_de(codigo: str) -> str | None:
        parada = paradas.get(codigo)
        return parada.localidad if parada is not None else None

    for bus_id in sorted(grupos):
        miembros = grupos[bus_id]
        if len(miembros) == 1:
            errores.append(
                f"bus:{bus_id} aparece en un solo viaje ({miembros[0].etiqueta}); "
                "¿errata en el identificador?"
            )
            continue

        sin_pareja = [
            m for m in miembros if not any(o is not m and _solapan(m, o) for o in miembros)
        ]
        if sin_pareja:
            errores.append(
                f"bus:{bus_id}: los viajes no coinciden en ningún día "
                f"({' / '.join(m.etiqueta for m in sin_pareja)})"
            )

        vistos: set[str] = set()

        # `registrar` solo se usa dentro de esta iteración, con su `vistos`.
        def registrar(mensaje: str) -> None:
            if mensaje not in vistos:  # noqa: B023
                vistos.add(mensaje)  # noqa: B023
                errores.append(mensaje)

        for i, a in enumerate(miembros):
            for b in miembros[i + 1 :]:
                if not _solapan(a, b):
                    continue
                par = f"{a.etiqueta} / {b.etiqueta}"
                if a.viaje.linea == b.viaje.linea:
                    registrar(
                        f"bus:{bus_id}: dos viajes de la misma línea "
                        f"'{a.viaje.linea}' con días solapados ({par}); "
                        "¿son dos autobuses?"
                    )
                locs_a = {loc_de(p.parada) for p in a.viaje.pasos} - {None}
                locs_b = {loc_de(p.parada) for p in b.viaje.pasos} - {None}
                comunes = locs_a & locs_b
                if len(comunes) < 2:
                    registrar(f"bus:{bus_id}: comparten menos de 2 localidades ({par})")
                    continue
                for loc in sorted(comunes):  # type: ignore[type-var]
                    seq_a = [p.parada for p in a.viaje.pasos if loc_de(p.parada) == loc]
                    seq_b = [p.parada for p in b.viaje.pasos if loc_de(p.parada) == loc]
                    if seq_a != seq_b:
                        nombre = localidades[loc].nombre if loc in localidades else loc
                        registrar(
                            f"bus:{bus_id}: paradas distintas en {nombre} "
                            f"({'+'.join(seq_a)} / {'+'.join(seq_b)}; {par})"
                        )
                codigos_comunes = [
                    p.parada for p in a.viaje.pasos if p.parada in {q.parada for q in b.viaje.pasos}
                ]
                for codigo, pa, pb in _horas_distintas_en_comunes(
                    a.viaje, b.viaje, codigos_comunes
                ):
                    registrar(
                        f"bus:{bus_id}: horas distintas en '{codigo}' "
                        f"({a.etiqueta}: {_texto_hora_paso(pa)} / "
                        f"{b.etiqueta}: {_texto_hora_paso(pb)})"
                    )


def _avisos_mismo_bus(
    infos: list[_InfoViaje],
    paradas: dict[str, Parada],
    lineas: dict[str, Linea],
    avisos: list[str],
) -> None:
    """Aviso heurístico: pares de viajes de líneas distintas y
    NO declarados como el mismo `bus:` que parecen el mismo autobús (2 o más
    localidades comunes en el mismo orden, días solapados y la misma hora en la
    primera parada común) pero discrepan más adelante. Solo avisa: la fusión
    del motor sigue siendo por horas idénticas. Un aviso por (línea, línea,
    primera parada común, parada discrepante), sin repetirlo por temporada."""
    codigos_de = [frozenset(p.parada for p in i.viaje.pasos) for i in infos]

    def nombre_linea(lid: str) -> str:
        linea = lineas.get(lid)
        return linea.nombre if linea is not None else lid

    def nombre_parada(codigo: str) -> str:
        parada = paradas.get(codigo)
        return parada.nombre if parada is not None else codigo

    claves: dict[tuple[str, str, str, str], dict[str, list[str]]] = {}
    cabeceras: dict[tuple[str, str, str, str], str] = {}
    for i, a in enumerate(infos):
        for j in range(i + 1, len(infos)):
            b = infos[j]
            if a.viaje.linea == b.viaje.linea:
                continue
            if a.viaje.bus is not None and a.viaje.bus == b.viaje.bus:
                continue
            comunes = codigos_de[i] & codigos_de[j]
            if len(comunes) < 2 or not _solapan(a, b):
                continue
            seq_a = [p.parada for p in a.viaje.pasos if p.parada in comunes]
            seq_b = [p.parada for p in b.viaje.pasos if p.parada in comunes]
            if seq_a != seq_b:
                continue
            locs = {paradas[c].localidad for c in seq_a if c in paradas}
            if len(locs) < 2:
                continue
            distintas = _horas_distintas_en_comunes(a.viaje, b.viaje, seq_a)
            if not distintas or distintas[0][0] == seq_a[0]:
                continue  # todo igual, o ya discrepa en la primera parada común
            primera = seq_a[0]
            codigo, pa, pb = distintas[0]
            clave = (a.viaje.linea, b.viaje.linea, primera, codigo)
            orden_a = [p.parada for p in a.viaje.pasos]
            paso_primero = a.viaje.pasos[orden_a.index(primera)]
            dias = (
                a.viaje.dias if a.viaje.dias == b.viaje.dias else f"{a.viaje.dias} / {b.viaje.dias}"
            )
            detalle = (
                f"{nombre_parada(primera)} {_texto_hora_paso(paso_primero)} en "
                f"ambas y {nombre_parada(codigo)} {_texto_hora_paso(pa)} frente a "
                f"{_texto_hora_paso(pb)}"
            )
            cabeceras[clave] = (
                f"{a.ruta}: posible mismo autobús con horas distintas: "
                f"'{nombre_linea(a.viaje.linea)}' y '{nombre_linea(b.viaje.linea)}'"
            )
            dias_previos = claves.setdefault(clave, {}).setdefault(detalle, [])
            if dias not in dias_previos:
                dias_previos.append(dias)

    for clave, detalles in claves.items():
        texto = "; ".join(f"{detalle} ({', '.join(dias)})" for detalle, dias in detalles.items())
        avisos.append(f"{cabeceras[clave]}: {texto} (no se fusionará)")


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

    datos_paradas = _cargar_yaml(paradas_path, errores)
    localidades, paradas = _validar_localidades_paradas(
        datos_paradas or {}, paradas_path, errores, avisos
    )
    pendientes_paradas = _validar_pendientes_paradas(
        datos_paradas or {}, paradas_path, errores, avisos
    )
    no_vendibles = _validar_no_vendibles(datos_paradas or {}, paradas_path, localidades, errores)

    datos_observaciones = _cargar_yaml(observaciones_path, errores)
    observaciones = _validar_observaciones(datos_observaciones or {}, observaciones_path, errores)

    calendario = _validar_calendario(directorio, errores, avisos, localidades)

    lineas: dict[str, Linea] = {}
    paradas_usadas: set[str] = set()
    infos_viaje: list[_InfoViaje] = []
    if lineas_dir.is_dir():
        for path in sorted(lineas_dir.glob("*.yaml")):
            lid = path.stem
            if not LINEA_ID_RE.match(lid):
                errores.append(
                    f"{path}: id de línea inválido '{lid}' (el nombre del "
                    "fichero solo puede tener minúsculas sin tilde, dígitos "
                    "y guiones)"
                )
            datos_linea = _cargar_yaml(path, errores)
            if datos_linea is None:
                continue
            linea = _validar_linea(
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

    _validar_localidades_pendientes(
        paradas_path,
        localidades,
        paradas,
        observaciones,
        pendientes_paradas,
        errores,
        avisos,
    )
    _validar_buses(infos_viaje, paradas, localidades, errores)
    _avisos_mismo_bus(infos_viaje, paradas, lineas, avisos)

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
