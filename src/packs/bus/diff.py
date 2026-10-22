"""packs/bus/diff.py — diferencias entre dos versiones de horarios/
en lenguaje de negocio (buscaBus/design.md, sección 2.3, "Cambios desde la versión
publicada").

Módulo puro: no toca disco, no invoca git, no lanza excepciones por
diferencias de negocio. Compara dos `Modelo` ya validados por
`formato.validar()` (los construye quien llama, típicamente
`tools/revision.py`). `tools/revision.py` es responsable de decidir si hay
una versión anterior o si es la primera versión: este módulo siempre recibe
dos `Modelo`s reales.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from packs.bus.formato import DIAS_INDIVIDUALES, GRUPOS_DIA, Modelo
from packs.bus.modelo import Linea, Paso, Viaje

_MESES_EN_PALABRAS = {
    1: "enero",
    2: "febrero",
    3: "marzo",
    4: "abril",
    5: "mayo",
    6: "junio",
    7: "julio",
    8: "agosto",
    9: "septiembre",
    10: "octubre",
    11: "noviembre",
    12: "diciembre",
}

_ESTADOS_EN_PALABRAS = {
    "horario": "hay servicio",
    "sin_servicio": "sin servicio",
    "sin_datos": "sin datos",
}

# Orden estable de las clases de día para recorrer los cambios de "dias".
_ORDEN_CLASES = DIAS_INDIVIDUALES

# Fraseo "en palabras" de cada clave de tabla (buscaBus/design.md sección 2.3). Se
# construye a partir de GRUPOS_DIA para no duplicar el catálogo de claves de
# formato.py, con los textos exactos que pide el diseño.
_CLASES_EN_PALABRAS = {
    "lunes": "lunes",
    "martes": "martes",
    "miercoles": "miércoles",
    "jueves": "jueves",
    "viernes": "viernes",
    "sabado": "sábado",
    "domingo": "domingo",
    "festivos": "festivos",
    "lunes-viernes": "lunes a viernes",
    "lunes-jueves": "lunes a jueves",
    "martes-viernes": "martes a viernes",
    "sabados-domingos": "sábados y domingos",
    "domingos-festivos": "domingos y festivos",
    "sabados-domingos-festivos": "sábados, domingos y festivos",
}

assert set(_CLASES_EN_PALABRAS) == set(GRUPOS_DIA), (
    "_CLASES_EN_PALABRAS debe cubrir exactamente las claves de GRUPOS_DIA (formato.py)"
)


def fecha_en_palabras(fecha: str) -> str:
    """'15/09' -> '15 de septiembre'. Si no tiene ese formato, se devuelve
    tal cual (nunca se adivina)."""
    fecha = fecha.strip()
    partes = fecha.split("/")
    if len(partes) != 2:
        return fecha
    try:
        dia = int(partes[0])
        mes = int(partes[1])
    except ValueError:
        return fecha
    nombre_mes = _MESES_EN_PALABRAS.get(mes)
    if nombre_mes is None:
        return fecha
    return f"{dia} de {nombre_mes}"


def rango_en_palabras(rango: str) -> str:
    """'15/09 - 22/06' -> 'del 15 de septiembre al 22 de junio'. 'todo el
    año' se deja igual."""
    rango = rango.strip()
    if rango.lower() in ("todo el año", "todo el ano"):
        return rango
    partes = [p.strip() for p in rango.split("-")]
    if len(partes) != 2:
        return rango
    return f"del {fecha_en_palabras(partes[0])} al {fecha_en_palabras(partes[1])}"


def clase_en_palabras(clase: str) -> str:
    return _CLASES_EN_PALABRAS.get(clase, clase)


def estado_en_palabras(estado: str) -> str:
    return _ESTADOS_EN_PALABRAS.get(estado, estado)


def _nombre_parada(modelo: Modelo, codigo: str) -> str:
    parada = modelo.paradas.get(codigo)
    return parada.nombre if parada is not None else codigo


def _hora_primer_paso(viaje: Viaje) -> str:
    return viaje.pasos[0].salida if viaje.pasos else ""


def _minutos(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


# Diferencia máxima (minutos) entre las horas del primer punto en común de
# dos viajes para considerarlos "el mismo viaje que cambió de hora" en vez de
# una alta y una baja independientes (buscaBus/design.md 8, "Correcciones de la fase
# 1", punto 3).
_UMBRAL_MINUTOS_EMPAREJADO = 30


def _firma_tabla(viaje: Viaje) -> tuple[str, str, str | None, str | None]:
    """(temporada, dias, primera parada de la cabecera, última parada de la
    cabecera) de la `Tabla` a la que pertenece `viaje`. Dos tablas con la
    misma firma en versiones distintas se consideran "la misma tabla" a
    efectos del diff (formato.py impide que haya dos tablas con la misma
    firma dentro de una misma línea)."""
    paradas = viaje.tabla.paradas
    primera = paradas[0] if paradas else None
    ultima = paradas[-1] if paradas else None
    return (viaje.temporada, viaje.dias, primera, ultima)


def _agrupar_por_firma(linea: Linea) -> dict[tuple[Any, ...], list[Viaje]]:
    grupos: dict[tuple[Any, ...], list[Viaje]] = {}
    for v in linea.viajes:
        grupos.setdefault(_firma_tabla(v), []).append(v)
    return grupos


def _clave_viaje(viaje: Viaje) -> tuple[Any, ...]:
    """Identidad de un viaje independiente del orden de sus pasos (para
    detectar viajes idénticos aunque la cabecera de su tabla se haya
    reordenado sin cambiar ningún dato). Incluye llegada, salida y `bus:`."""
    pasos = frozenset(
        (p.parada, p.llegada, p.salida, frozenset(p.observaciones)) for p in viaje.pasos
    )
    return (
        pasos,
        frozenset(viaje.observaciones),
        frozenset(viaje.pendientes),
        viaje.bus,
    )


# El emparejado usa la salida de cada parada común (buscaBus/design.md 2.3): la hora
# a la que el autobús sale de ella.
def _diferencia_primer_paso_comun(viaje_a: Viaje, viaje_b: Viaje) -> int | None:
    horas_b = {p.parada: p.salida for p in viaje_b.pasos}
    for paso in viaje_a.pasos:
        hora_b = horas_b.get(paso.parada)
        if hora_b is not None:
            return abs(_minutos(paso.salida) - _minutos(hora_b))
    return None


def _emparejar_por_cercania(
    viajes_ant: list[Viaje], viajes_act: list[Viaje]
) -> tuple[list[tuple[Viaje, Viaje]], list[Viaje], list[Viaje]]:
    """Empareja viajes por cercanía de horas en su primer punto en común
    (≤ _UMBRAL_MINUTOS_EMPAREJADO), voraz por menor diferencia y, en caso de
    empate, por la hora más temprana. Devuelve (pares, sobrantes_ant,
    sobrantes_act)."""
    restante_ant = list(viajes_ant)
    restante_act = list(viajes_act)
    pares: list[tuple[Viaje, Viaje]] = []
    while restante_ant and restante_act:
        mejor: tuple[Any, ...] | None = None
        mejor_ij: tuple[int, int] | None = None
        for i, v_ant in enumerate(restante_ant):
            for j, v_act in enumerate(restante_act):
                dif = _diferencia_primer_paso_comun(v_ant, v_act)
                if dif is None or dif > _UMBRAL_MINUTOS_EMPAREJADO:
                    continue
                clave = (dif, _hora_primer_paso(v_ant), _hora_primer_paso(v_act))
                if mejor is None or clave < mejor:
                    mejor = clave
                    mejor_ij = (i, j)
        if mejor_ij is None:
            break
        i, j = mejor_ij
        pares.append((restante_ant.pop(i), restante_act.pop(j)))
    return pares, restante_ant, restante_act


def _comparar_temporadas(nombre_linea: str, anterior: Linea, actual: Linea) -> list[str]:
    mensajes: list[str] = []
    rangos_anterior = {t.nombre: t.rango for t in anterior.temporadas}
    rangos_actual = {t.nombre: t.rango for t in actual.temporadas}
    for nombre_temp in sorted(set(rangos_anterior) | set(rangos_actual)):
        r_ant = rangos_anterior.get(nombre_temp)
        r_act = rangos_actual.get(nombre_temp)
        if r_ant is None:
            assert r_act is not None  # está en uno de los dos
            mensajes.append(
                f"{nombre_linea}: se añade la temporada '{nombre_temp}' "
                f"({rango_en_palabras(r_act)})."
            )
        elif r_act is None:
            mensajes.append(
                f"{nombre_linea}: se quita la temporada '{nombre_temp}' "
                f"({rango_en_palabras(r_ant)})."
            )
        elif r_ant != r_act:
            mensajes.append(
                f"{nombre_linea}: la temporada '{nombre_temp}' pasa de "
                f"{rango_en_palabras(r_ant)} a {rango_en_palabras(r_act)}."
            )
    return mensajes


def _comparar_dias(nombre_linea: str, anterior: Linea, actual: Linea) -> list[str]:
    mensajes: list[str] = []
    temporadas = sorted(set(anterior.dias) | set(actual.dias))
    for nombre_temp in temporadas:
        estados_ant = anterior.dias.get(nombre_temp, {})
        estados_act = actual.dias.get(nombre_temp, {})
        for clase in _ORDEN_CLASES:
            e_ant = estados_ant.get(clase)
            e_act = estados_act.get(clase)
            if e_ant is None or e_act is None:
                continue
            if e_ant != e_act:
                mensajes.append(
                    f"{nombre_linea}, temporada '{nombre_temp}', "
                    f"{clase_en_palabras(clase)}: pasa de "
                    f"{estado_en_palabras(e_ant)} a {estado_en_palabras(e_act)}."
                )
    return mensajes


def _extremos_viaje(modelo: Modelo, viaje: Viaje) -> str:
    if not viaje.pasos:
        return ""
    origen = _nombre_parada(modelo, viaje.pasos[0].parada)
    destino = _nombre_parada(modelo, viaje.pasos[-1].parada)
    hora = viaje.pasos[0].salida
    return f"{hora} de {origen} a {destino}"


def _comparar_viajes(
    nombre_linea: str,
    anterior: Linea,
    actual: Linea,
    modelo_anterior: Modelo,
    modelo_actual: Modelo,
) -> list[str]:
    mensajes: list[str] = []

    grupos_ant = _agrupar_por_firma(anterior)
    grupos_act = _agrupar_por_firma(actual)

    for firma in sorted(
        set(grupos_ant) | set(grupos_act),
        key=lambda f: (f[0], f[1], f[2] or "", f[3] or ""),
    ):
        temporada, dias, _primera, _ultima = firma
        viajes_ant = grupos_ant.get(firma)
        viajes_act = grupos_act.get(firma)

        if viajes_ant is None:
            assert viajes_act is not None  # la firma está en uno de los dos
            resumen = "; ".join(_extremos_viaje(modelo_actual, v) for v in viajes_act)
            mensajes.append(
                f"{nombre_linea}, {temporada}, {clase_en_palabras(dias)}: "
                f"tabla añadida ({resumen})."
            )
            continue
        if viajes_act is None:
            resumen = "; ".join(_extremos_viaje(modelo_anterior, v) for v in viajes_ant)
            mensajes.append(
                f"{nombre_linea}, {temporada}, {clase_en_palabras(dias)}: "
                f"tabla quitada ({resumen})."
            )
            continue

        mensajes.extend(
            _comparar_tabla(
                nombre_linea,
                temporada,
                dias,
                viajes_ant,
                viajes_act,
                modelo_anterior,
                modelo_actual,
            )
        )

    return mensajes


def _comparar_tabla(
    nombre_linea: str,
    temporada: str,
    dias: str,
    viajes_ant: list[Viaje],
    viajes_act: list[Viaje],
    modelo_anterior: Modelo,
    modelo_actual: Modelo,
) -> list[str]:
    mensajes: list[str] = []

    restante_ant = list(viajes_ant)
    restante_act = list(viajes_act)

    # 1. Viajes idénticos en ambos lados: no generan ningún mensaje. Se
    # comparan por contenido (parada+hora+observaciones), no por posición, así
    # que reordenar la cabecera de la tabla sin cambiar datos no genera ruido.
    for v_act in list(restante_act):
        clave = _clave_viaje(v_act)
        for v_ant in restante_ant:
            if _clave_viaje(v_ant) == clave:
                restante_ant.remove(v_ant)
                restante_act.remove(v_act)
                break

    # 2. El resto se empareja por cercanía de horas: quitar un viaje de en
    # medio de un grupo no debe leerse como que otro viaje "cambió de hora".
    pares, restante_ant, restante_act = _emparejar_por_cercania(restante_ant, restante_act)

    for viaje_ant, viaje_act in pares:
        mensajes.extend(
            _comparar_viaje_pareado(
                nombre_linea,
                temporada,
                dias,
                viaje_ant,
                viaje_act,
                modelo_anterior,
                modelo_actual,
            )
        )

    for viaje_act in sorted(restante_act, key=_hora_primer_paso):
        mensajes.append(
            f"{nombre_linea}, {temporada}, {clase_en_palabras(dias)}: "
            f"viaje añadido ({_extremos_viaje(modelo_actual, viaje_act)})."
        )
    for viaje_ant in sorted(restante_ant, key=_hora_primer_paso):
        mensajes.append(
            f"{nombre_linea}, {temporada}, {clase_en_palabras(dias)}: "
            f"viaje quitado ({_extremos_viaje(modelo_anterior, viaje_ant)})."
        )

    return mensajes


# Fraseo del verbo según la posición del paso en el viaje *actual* (buscaBus/design.md
# 8, "Correcciones de la fase 1", punto 7: no siempre es "la salida").
_VERBO_POR_POSICION = {
    "primera": "Sale de",
    "intermedia": "Pasa por",
    "ultima": "Llega a",
}


def _posicion(indice: int, total: int) -> str:
    if indice == 0:
        return "primera"
    if indice == total - 1:
        return "ultima"
    return "intermedia"


def _comparar_viaje_pareado(
    nombre_linea: str,
    temporada: str,
    dias: str,
    viaje_ant: Viaje,
    viaje_act: Viaje,
    modelo_anterior: Modelo,
    modelo_actual: Modelo,
) -> list[str]:
    mensajes: list[str] = []
    pasos_ant_por_codigo = {p.parada: p for p in viaje_ant.pasos}
    pasos_act_por_codigo = {p.parada: p for p in viaje_act.pasos}
    total = len(viaje_act.pasos)

    for indice, paso_act in enumerate(viaje_act.pasos):
        nombre_parada = _nombre_parada(modelo_actual, paso_act.parada)
        paso_ant = pasos_ant_por_codigo.get(paso_act.parada)
        prefijo = f"{nombre_linea}, {temporada}, {clase_en_palabras(dias)}: "
        if paso_ant is None:
            if paso_act.llegada != paso_act.salida:
                mensajes.append(
                    f"{prefijo}ahora para en {nombre_parada}: llega a las "
                    f"{paso_act.llegada} y sale a las {paso_act.salida}."
                )
            else:
                mensajes.append(f"{prefijo}ahora para en {nombre_parada} a las {paso_act.salida}.")
            continue
        mensajes.extend(
            _comparar_horas_paso(prefijo, nombre_parada, paso_ant, paso_act, indice, total)
        )
        mensajes.extend(
            _comparar_observaciones_paso(
                nombre_linea,
                temporada,
                dias,
                nombre_parada,
                paso_ant,
                paso_act,
                modelo_anterior,
                modelo_actual,
            )
        )

    for paso_ant in viaje_ant.pasos:
        if paso_ant.parada not in pasos_act_por_codigo:
            nombre_parada = _nombre_parada(modelo_anterior, paso_ant.parada)
            mensajes.append(
                f"{nombre_linea}, {temporada}, {clase_en_palabras(dias)}: ya no "
                f"para en {nombre_parada}."
            )

    mensajes.extend(
        _comparar_observaciones_viaje(
            nombre_linea,
            temporada,
            dias,
            viaje_ant,
            viaje_act,
            modelo_anterior,
            modelo_actual,
        )
    )
    mensajes.extend(_comparar_bus(nombre_linea, temporada, dias, viaje_ant, viaje_act))
    return mensajes


def _comparar_horas_paso(
    prefijo: str,
    nombre_parada: str,
    paso_ant: Paso,
    paso_act: Paso,
    indice: int,
    total: int,
) -> list[str]:
    """Cambios de hora de una parada en lenguaje de negocio. Con llegada y
    salida iguales (celda simple) en ambas versiones, el texto de siempre;
    si alguna versión tiene espera (llegada distinta de salida), se dice cuál
    de las dos horas cambia."""
    ant_simple = paso_ant.llegada == paso_ant.salida
    act_simple = paso_act.llegada == paso_act.salida
    if ant_simple and act_simple:
        if paso_ant.salida == paso_act.salida:
            return []
        verbo = _VERBO_POR_POSICION[_posicion(indice, total)]
        return [
            f"{prefijo}{verbo} {nombre_parada}: de las {paso_ant.salida} a las {paso_act.salida}."
        ]
    if ant_simple:
        return [
            f"{prefijo}en {nombre_parada}, ahora llega a las {paso_act.llegada} "
            f"y sale a las {paso_act.salida} (antes {paso_ant.salida})."
        ]
    if act_simple:
        return [
            f"{prefijo}en {nombre_parada}, ahora llega y sale a las "
            f"{paso_act.salida} (antes llegaba a las {paso_ant.llegada} y salía "
            f"a las {paso_ant.salida})."
        ]
    mensajes: list[str] = []
    if paso_ant.llegada != paso_act.llegada:
        mensajes.append(
            f"{prefijo}en {nombre_parada}, la llegada pasa de las "
            f"{paso_ant.llegada} a las {paso_act.llegada}."
        )
    if paso_ant.salida != paso_act.salida:
        mensajes.append(
            f"{prefijo}en {nombre_parada}, la salida pasa de las "
            f"{paso_ant.salida} a las {paso_act.salida}."
        )
    return mensajes


def _comparar_bus(
    nombre_linea: str,
    temporada: str,
    dias: str,
    viaje_ant: Viaje,
    viaje_act: Viaje,
) -> list[str]:
    prefijo = f"{nombre_linea}, {temporada}, {clase_en_palabras(dias)}: "
    if viaje_ant.bus == viaje_act.bus:
        return []
    if viaje_ant.bus is None:
        return [
            f"{prefijo}ahora se marca como el mismo autobús que otros viajes ('{viaje_act.bus}')."
        ]
    if viaje_act.bus is None:
        return [
            f"{prefijo}ya no se marca como el mismo autobús que otros viajes ('{viaje_ant.bus}')."
        ]
    return [f"{prefijo}el identificador de autobús pasa de '{viaje_ant.bus}' a '{viaje_act.bus}'."]


def _texto_observacion(oid: str, actual: Modelo, anterior: Modelo) -> str:
    """Texto de negocio de una observación: el del modelo actual; si ya no
    existe, el del anterior; si no está en ninguno, el propio id."""
    for modelo in (actual, anterior):
        obs = modelo.observaciones.get(oid)
        if obs is not None:
            return obs.texto
    return oid


def _comparar_observaciones_paso(
    nombre_linea: str,
    temporada: str,
    dias: str,
    nombre_parada: str,
    paso_ant: Paso,
    paso_act: Paso,
    modelo_anterior: Modelo,
    modelo_actual: Modelo,
) -> list[str]:
    mensajes: list[str] = []
    obs_ant = set(paso_ant.observaciones)
    obs_act = set(paso_act.observaciones)
    for oid in sorted(obs_act - obs_ant):
        mensajes.append(
            f"{nombre_linea}, {temporada}, {clase_en_palabras(dias)}, en "
            f"{nombre_parada}: se añade la observación "
            f"«{_texto_observacion(oid, modelo_actual, modelo_anterior)}»."
        )
    for oid in sorted(obs_ant - obs_act):
        mensajes.append(
            f"{nombre_linea}, {temporada}, {clase_en_palabras(dias)}, en "
            f"{nombre_parada}: se quita la observación "
            f"«{_texto_observacion(oid, modelo_actual, modelo_anterior)}»."
        )
    return mensajes


def _comparar_observaciones_viaje(
    nombre_linea: str,
    temporada: str,
    dias: str,
    viaje_ant: Viaje,
    viaje_act: Viaje,
    modelo_anterior: Modelo,
    modelo_actual: Modelo,
) -> list[str]:
    mensajes: list[str] = []
    obs_ant = set(viaje_ant.observaciones)
    obs_act = set(viaje_act.observaciones)
    for oid in sorted(obs_act - obs_ant):
        texto = _texto_observacion(oid, modelo_actual, modelo_anterior)
        mensajes.append(
            f"{nombre_linea}, {temporada}, {clase_en_palabras(dias)}: se añade "
            f"la observación «{texto}»."
        )
    for oid in sorted(obs_ant - obs_act):
        texto = _texto_observacion(oid, modelo_actual, modelo_anterior)
        mensajes.append(
            f"{nombre_linea}, {temporada}, {clase_en_palabras(dias)}: se quita "
            f"la observación «{texto}»."
        )
    return mensajes


def _avisos_cambiados(anterior: Linea, actual: Linea) -> tuple[list[str], list[str]]:
    """(añadidos, quitados) ids de aviso de línea, ordenados."""
    ant = set(anterior.avisos)
    act = set(actual.avisos)
    return sorted(act - ant), sorted(ant - act)


def _comparar_avisos(
    nombre_linea: str,
    anterior: Linea,
    actual: Linea,
    modelo_anterior: Modelo,
    modelo_actual: Modelo,
    agrupados: frozenset[tuple[str, str]] | set[tuple[str, str]],
) -> list[str]:
    """Avisos de línea. Los (accion, id) que ya se dicen agrupados en el
    bloque general se omiten aquí."""
    mensajes: list[str] = []
    anadidos, quitados = _avisos_cambiados(anterior, actual)
    for oid in anadidos:
        if ("añade", oid) in agrupados:
            continue
        texto = _texto_observacion(oid, modelo_actual, modelo_anterior)
        mensajes.append(f"{nombre_linea}: se añade el aviso «{texto}».")
    for oid in quitados:
        if ("quita", oid) in agrupados:
            continue
        texto = _texto_observacion(oid, modelo_actual, modelo_anterior)
        mensajes.append(f"{nombre_linea}: se quita el aviso «{texto}».")
    return mensajes


def _comparar_linea(
    anterior: Linea,
    actual: Linea,
    modelo_anterior: Modelo,
    modelo_actual: Modelo,
    agrupados: frozenset[tuple[str, str]] | set[tuple[str, str]] = frozenset(),
) -> list[str]:
    nombre_linea = actual.nombre
    mensajes: list[str] = []
    if anterior.titulo != actual.titulo:
        mensajes.append(
            f'{nombre_linea}: en el bot se mostrará como "{actual.titulo}" '
            f'(antes "{anterior.titulo}")'
        )
    mensajes.extend(
        _comparar_avisos(nombre_linea, anterior, actual, modelo_anterior, modelo_actual, agrupados)
    )
    mensajes.extend(_comparar_temporadas(nombre_linea, anterior, actual))
    mensajes.extend(_comparar_dias(nombre_linea, anterior, actual))
    mensajes.extend(
        _comparar_viajes(nombre_linea, anterior, actual, modelo_anterior, modelo_actual)
    )
    return mensajes


# A partir de este número de líneas con el mismo aviso añadido (o quitado) se
# dice en una sola frase en el bloque general.
_MIN_LINEAS_AVISO_AGRUPADO = 3


def _avisos_agrupados(anterior: Modelo, actual: Modelo) -> tuple[list[str], set[tuple[str, str]]]:
    """Frases del aviso añadido/quitado en >= 3 líneas, y el conjunto de
    (accion, id) agrupados para no repetirlos línea a línea."""
    por_cambio: dict[tuple[str, str], list[str]] = {}
    for lid in sorted(set(anterior.lineas) & set(actual.lineas)):
        linea_ant = anterior.lineas[lid]
        linea_act = actual.lineas[lid]
        anadidos, quitados = _avisos_cambiados(linea_ant, linea_act)
        for oid in anadidos:
            por_cambio.setdefault(("añade", oid), []).append(linea_act.nombre)
        for oid in quitados:
            por_cambio.setdefault(("quita", oid), []).append(linea_act.nombre)
    frases: list[str] = []
    agrupados: set[tuple[str, str]] = set()
    for accion in ("añade", "quita"):
        for (acc, oid), nombres in sorted(por_cambio.items()):
            if acc != accion or len(nombres) < _MIN_LINEAS_AVISO_AGRUPADO:
                continue
            texto = _texto_observacion(oid, actual, anterior)
            frases.append(
                f"Se {accion} el aviso «{texto}» a {len(nombres)} líneas: {', '.join(nombres)}."
            )
            agrupados.add((acc, oid))
    return frases, agrupados


def _fecha_dia_mes(d: date) -> str:
    return f"{d.day} de {_MESES_EN_PALABRAS[d.month]}"


def _fecha_larga(d: date) -> str:
    return f"{_fecha_dia_mes(d)} de {d.year}"


def _comparar_calendario(anterior: Modelo, actual: Modelo) -> list[str]:
    cal_ant = anterior.calendario
    cal_act = actual.calendario
    if cal_ant is None or cal_act is None:
        return []
    mensajes: list[str] = []

    fest_ant = set(cal_ant.festivos.items())
    fest_act = set(cal_act.festivos.items())
    for fecha, nombre in sorted(fest_act - fest_ant):
        mensajes.append(f"Se añade el festivo «{nombre}» ({_fecha_larga(fecha)}).")
    for fecha, nombre in sorted(fest_ant - fest_act):
        mensajes.append(f"Se quita el festivo «{nombre}» ({_fecha_larga(fecha)}).")

    def _nombre_localidad(lid: str) -> str:
        for modelo in (anterior, actual):
            loc = modelo.localidades.get(lid)
            if loc is not None:
                return loc.nombre
        return lid

    locales_ant = {(lid, f, n) for lid, d in cal_ant.festivos_locales.items() for f, n in d.items()}
    locales_act = {(lid, f, n) for lid, d in cal_act.festivos_locales.items() for f, n in d.items()}
    for lid, fecha, nombre in sorted(locales_act - locales_ant):
        mensajes.append(
            f"Se añade el festivo local «{nombre}» en {_nombre_localidad(lid)} "
            f"({_fecha_larga(fecha)})."
        )
    for lid, fecha, nombre in sorted(locales_ant - locales_act):
        mensajes.append(
            f"Se quita el festivo local «{nombre}» en {_nombre_localidad(lid)} "
            f"({_fecha_larga(fecha)})."
        )

    sin_ant = cal_ant.sin_servicio_todas_las_lineas
    sin_act = cal_act.sin_servicio_todas_las_lineas
    for mes, dia in sorted(sin_act - sin_ant, key=lambda md: (md[0], md[1])):
        mensajes.append(
            f"Se añade el {dia} de {_MESES_EN_PALABRAS[mes]} como día sin "
            "servicio en ninguna línea."
        )
    for mes, dia in sorted(sin_ant - sin_act, key=lambda md: (md[0], md[1])):
        mensajes.append(
            f"Se quita el {dia} de {_MESES_EN_PALABRAS[mes]} como día sin "
            "servicio en ninguna línea."
        )

    for etiqueta, v_ant, v_act in (
        ("El inicio de las clases", cal_ant.inicio_clases, cal_act.inicio_clases),
        ("El fin de las clases", cal_ant.fin_clases, cal_act.fin_clases),
        (
            "El calendario empieza a valer",
            cal_ant.vigencia_inicio,
            cal_act.vigencia_inicio,
        ),
        ("El calendario deja de valer", cal_ant.vigencia_fin, cal_act.vigencia_fin),
    ):
        if v_ant != v_act:
            mensajes.append(f"{etiqueta} pasa del {_fecha_larga(v_ant)} al {_fecha_larga(v_act)}.")
    return mensajes


def _comparar_paradas_y_localidades(anterior: Modelo, actual: Modelo) -> list[str]:
    mensajes: list[str] = []

    # Localidades
    for lid in sorted(set(actual.localidades) - set(anterior.localidades)):
        mensajes.append(f"Se añade la localidad «{actual.localidades[lid].nombre}».")
    for lid in sorted(set(anterior.localidades) - set(actual.localidades)):
        mensajes.append(f"Se quita la localidad «{anterior.localidades[lid].nombre}».")
    for lid in sorted(set(anterior.localidades) & set(actual.localidades)):
        loc_ant = anterior.localidades[lid]
        loc_act = actual.localidades[lid]
        if loc_ant.nombre != loc_act.nombre:
            mensajes.append(f"La localidad «{loc_ant.nombre}» pasa a llamarse «{loc_act.nombre}».")
        for alias in sorted(set(loc_act.alias) - set(loc_ant.alias)):
            mensajes.append(f"{loc_act.nombre}: se añade el alias «{alias}».")
        for alias in sorted(set(loc_ant.alias) - set(loc_act.alias)):
            mensajes.append(f"{loc_act.nombre}: se quita el alias «{alias}».")

    # Paradas
    for cod in sorted(set(actual.paradas) - set(anterior.paradas)):
        parada = actual.paradas[cod]
        loc = actual.localidades.get(parada.localidad)
        nombre_loc = loc.nombre if loc is not None else parada.localidad
        mensajes.append(f"Se añade la parada «{parada.nombre}» (localidad {nombre_loc}).")
    for cod in sorted(set(anterior.paradas) - set(actual.paradas)):
        mensajes.append(f"Se quita la parada «{anterior.paradas[cod].nombre}».")
    for cod in sorted(set(anterior.paradas) & set(actual.paradas)):
        p_ant = anterior.paradas[cod]
        p_act = actual.paradas[cod]
        if p_ant.nombre != p_act.nombre:
            mensajes.append(f"La parada «{p_ant.nombre}» pasa a llamarse «{p_act.nombre}».")

    # Pares de localidades sin venta de billetes
    def _par_en_palabras(par: frozenset[str], modelo: Modelo, otro: Modelo) -> str:
        nombres = []
        for lid in par:
            loc = modelo.localidades.get(lid) or otro.localidades.get(lid)
            nombres.append(loc.nombre if loc is not None else lid)
        return " y ".join(sorted(nombres))

    for par in sorted(actual.no_vendibles - anterior.no_vendibles, key=sorted):
        mensajes.append(
            f"Ya no se venden billetes entre {_par_en_palabras(par, actual, anterior)}."
        )
    for par in sorted(anterior.no_vendibles - actual.no_vendibles, key=sorted):
        mensajes.append(
            f"Vuelven a venderse billetes entre {_par_en_palabras(par, anterior, actual)}."
        )
    return mensajes


def _comparar_textos_observaciones(anterior: Modelo, actual: Modelo) -> list[str]:
    mensajes: list[str] = []
    for oid in sorted(set(anterior.observaciones) & set(actual.observaciones)):
        t_ant = anterior.observaciones[oid].texto
        t_act = actual.observaciones[oid].texto
        if t_ant != t_act:
            mensajes.append(f"El texto de la observación «{t_ant}» pasa a «{t_act}».")
    return mensajes


def comparar(anterior: Modelo, actual: Modelo) -> list[str]:
    """Devuelve una lista de frases en lenguaje de negocio con las
    diferencias entre `anterior` y `actual`. Ambos deben ser `Modelo`s reales
    ya validados; nunca se llama con `None` (eso lo decide quien invoca este
    módulo, típicamente `tools/revision.py`, que resuelve "primera versión"
    antes de llamar aquí).

    Orden: bloque general (paradas y localidades, calendario, textos de
    observaciones, avisos agrupados) y después línea a línea."""
    mensajes: list[str] = []
    mensajes.extend(_comparar_paradas_y_localidades(anterior, actual))
    mensajes.extend(_comparar_calendario(anterior, actual))
    mensajes.extend(_comparar_textos_observaciones(anterior, actual))
    frases_agrupadas, agrupados = _avisos_agrupados(anterior, actual)
    mensajes.extend(frases_agrupadas)

    ids_lineas = sorted(set(anterior.lineas) | set(actual.lineas))
    for lid in ids_lineas:
        linea_ant = anterior.lineas.get(lid)
        linea_act = actual.lineas.get(lid)
        if linea_ant is None:
            assert linea_act is not None  # el id está en una de las dos versiones
            mensajes.append(f"Línea nueva: {linea_act.nombre}.")
        elif linea_act is None:
            mensajes.append(f"Línea eliminada: {linea_ant.nombre}.")
        else:
            mensajes.extend(_comparar_linea(linea_ant, linea_act, anterior, actual, agrupados))
    return mensajes
