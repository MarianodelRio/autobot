"""packs/bus/query.py — motor de consulta.

Puro: no hace E/S ni lee el reloj. `ahora` siempre se recibe como parámetro
(nunca `datetime.now()` dentro de este módulo), para que las pruebas sean
deterministas y para no acoplar el motor a una zona horaria concreta.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Literal

from core.dates import minutes_of, parse_hhmm
from packs.bus import calendario as calendario_servicio
from packs.bus import formato
from packs.bus.calendario import InfoDia
from packs.bus.loader import Horarios
from packs.bus.modelo import Linea, Temporada, Viaje

# Número de días hacia delante en los que se busca la siguiente fecha con
# servicio cuando la fecha pedida no tiene salidas.
SIGUIENTE_CON_SERVICIO_DIAS = 45

EstadoConsulta = Literal["con_salidas", "sin_servicio", "sin_datos", "sin_trayecto", "no_vendible"]


@dataclass(frozen=True)
class Salida:
    hora_salida: time
    hora_llegada: time
    duracion_min: int
    parada_origen: str
    parada_destino: str
    lineas: tuple[str, ...]
    notas: tuple[str, ...] = ()
    ya_salio: bool = False


@dataclass(frozen=True)
class Consulta:
    estado: EstadoConsulta
    salidas: tuple[Salida, ...]
    info_dia: InfoDia | None
    temporadas: tuple[tuple[str, Temporada], ...]
    lineas_sin_datos: tuple[str, ...]
    fuera_de_calendario: bool
    siguiente_con_servicio: date | None
    # True si el día es de sin servicio en ninguna línea .
    sin_servicio_general: bool = False
    # (nombre, id de localidad) si alguna línea que cubre el par usó un
    # festivo local ese día .
    festivo_local: tuple[str, str] | None = None


@dataclass(frozen=True)
class _Resolucion:
    estado: EstadoConsulta
    salidas: list[Salida]
    info: InfoDia | None
    temporadas: tuple[tuple[str, Temporada], ...]
    lineas_sin_datos: tuple[str, ...]
    fuera_de_calendario: bool
    sin_servicio_general: bool = False
    festivo_local: tuple[str, str] | None = None


def _localidades_del_viaje(horarios: Horarios, viaje: Viaje) -> list[str | None]:
    modelo = horarios.modelo
    localidades: list[str | None] = []
    for paso in viaje.pasos:
        parada = modelo.paradas.get(paso.parada)
        localidades.append(parada.localidad if parada is not None else None)
    return localidades


def _emparejar(
    horarios: Horarios, viaje: Viaje, origen: str, destino: str
) -> tuple[int, int] | None:
    """Índice del paso de origen y de destino en `viaje.pasos` para el par
    (origen, destino), o None si el viaje no los conecta en ese sentido.

    La parada de destino es la PRIMERA de la localidad de destino en el
    orden del viaje; la de origen es la ÚLTIMA de la localidad de origen
    antes de esa parada de destino (el tramo más corto posible)."""
    modelo = horarios.modelo
    idx_destino = None
    for i, paso in enumerate(viaje.pasos):
        parada = modelo.paradas.get(paso.parada)
        if parada is not None and parada.localidad == destino:
            idx_destino = i
            break
    if idx_destino is None:
        return None

    idx_origen = None
    for i in range(idx_destino - 1, -1, -1):
        parada = modelo.paradas.get(viaje.pasos[i].parada)
        if parada is not None and parada.localidad == origen:
            idx_origen = i
            break
    if idx_origen is None:
        return None

    return idx_origen, idx_destino


def _viajes_candidatos_por_localidad(horarios: Horarios, origen: str, destino: str) -> list[Viaje]:
    """Viajes que paran en alguna parada de `origen` y en alguna parada de
    `destino` (en cualquier orden), usando los índices de `horarios` en vez
    de recorrer todas las líneas y viajes. No confirma el sentido del
    trayecto: eso lo hace `_emparejar` sobre cada candidato.

    El orden devuelto es el de `horarios.viajes` (el de `modelo.lineas` y,
    dentro de cada línea, el de `linea.viajes`), así la agrupación por línea y
    por salida en `_resolver_fecha` no cambia respecto al escaneo completo."""
    en_destino = set(horarios.localidad_viajes_idx.get(destino, ()))
    if not en_destino:
        return []
    return [
        horarios.viajes[i] for i in horarios.localidad_viajes_idx.get(origen, ()) if i in en_destino
    ]


@dataclass(frozen=True)
class _Tramo:
    """Un viaje que conecta el par (origen, destino), con todo lo que no
    depende de la fecha ya resuelto: horas y paradas del tramo, y notas."""

    clases: frozenset[str]  # clases de día en las que circula (de `viaje.dias`)
    hora_salida: time
    hora_llegada: time
    parada_origen: str
    parada_destino: str
    notas: tuple[str, ...]
    solo_viernes_lectivo: bool


@dataclass(frozen=True)
class _LineaDelPar:
    """Tramos de una línea que conecta el par, por temporada."""

    linea: Linea
    por_temporada: dict[str, tuple[_Tramo, ...]]


def _tramo(horarios: Horarios, linea: Linea, viaje: Viaje, par: tuple[int, int]) -> _Tramo:
    """Construye el tramo de `viaje`: hora de salida/llegada ya como `time` y las
    observaciones que le aplican (de línea, de viaje y de las dos paradas), con
    su texto resuelto. Ningún pendiente (`Pnn`) llega nunca aquí: son solo para
    negocio/validador."""
    i_origen, i_destino = par
    paso_origen = viaje.pasos[i_origen]
    paso_destino = viaje.pasos[i_destino]
    ids = [
        *linea.avisos,
        *viaje.observaciones,
        *paso_origen.observaciones,
        *paso_destino.observaciones,
    ]
    notas: list[str] = []
    solo_viernes_lectivo = False
    for oid in ids:
        obs = horarios.modelo.observaciones.get(oid)
        if obs is None:
            continue
        solo_viernes_lectivo = solo_viernes_lectivo or obs.id == "solo_viernes_lectivo"
        texto = formato.texto_observacion(obs, linea)
        if texto not in notas:
            notas.append(texto)
    return _Tramo(
        clases=formato.GRUPOS_DIA.get(viaje.dias, frozenset()),
        hora_salida=parse_hhmm(paso_origen.salida),
        hora_llegada=parse_hhmm(paso_destino.llegada),
        parada_origen=paso_origen.parada,
        parada_destino=paso_destino.parada,
        notas=tuple(notas),
        solo_viernes_lectivo=solo_viernes_lectivo,
    )


def _lineas_del_par(horarios: Horarios, origen: str, destino: str) -> tuple[_LineaDelPar, ...]:
    """Líneas que conectan `origen` con `destino` en algún viaje, con sus tramos.
    Solo depende del par, no de la fecha: se calcula una vez por par y se
    guarda en `horarios.cache_pares`, porque listar varios días o buscar el
    siguiente día con servicio resuelve muchas fechas para el mismo par."""
    clave = (origen, destino)
    cacheado: tuple[_LineaDelPar, ...] | None = horarios.cache_pares.get(clave)
    if cacheado is not None:
        return cacheado

    por_linea: dict[str, list[Viaje]] = {}
    for viaje in _viajes_candidatos_por_localidad(horarios, origen, destino):
        por_linea.setdefault(viaje.linea, []).append(viaje)

    resultado: list[_LineaDelPar] = []
    for lid, viajes in por_linea.items():
        linea = horarios.modelo.lineas[lid]
        por_temporada: dict[str, list[_Tramo]] = {}
        for viaje in viajes:
            par = _emparejar(horarios, viaje, origen, destino)
            if par is not None:
                por_temporada.setdefault(viaje.temporada, []).append(
                    _tramo(horarios, linea, viaje, par)
                )
        # Una línea con viajes candidatos pero que no conecta el par en ningún
        # viaje no interviene en la consulta.
        if por_temporada:
            resultado.append(
                _LineaDelPar(linea, {t: tuple(tramos) for t, tramos in por_temporada.items()})
            )
    cacheado = tuple(resultado)
    horarios.cache_pares[clave] = cacheado
    return cacheado


@dataclass
class _Acumulado:
    """Una salida provisional: varias líneas con las mismas horas y paradas se
    fusionan en una."""

    tramo: _Tramo
    lineas: list[str] = field(default_factory=list)
    notas: list[str] = field(default_factory=list)


def _resolver_fecha(horarios: Horarios, origen: str, destino: str, fecha: date) -> _Resolucion:
    """Precedencia: sin_trayecto, sin_servicio en
    ninguna línea, fuera de vigencia (sin_datos), líneas."""
    calendario = horarios.modelo.calendario
    assert calendario is not None

    fuera_de_vigencia = fecha < calendario.vigencia_inicio or fecha > calendario.vigencia_fin
    lineas = _lineas_del_par(horarios, origen, destino)

    if not lineas:
        info = None if fuera_de_vigencia else calendario_servicio.info_dia(calendario, fecha)
        return _Resolucion("sin_trayecto", [], info, (), (), fuera_de_vigencia)

    if (fecha.month, fecha.day) in calendario.sin_servicio_todas_las_lineas:
        info = calendario_servicio.info_dia(calendario, fecha, permitir_fuera_de_vigencia=True)
        return _Resolucion("sin_servicio", [], info, (), (), False, sin_servicio_general=True)

    if fuera_de_vigencia:
        return _Resolucion("sin_datos", [], None, (), (), True)

    info = calendario_servicio.info_dia(calendario, fecha)

    lineas_sin_datos: set[str] = set()
    temporadas_usadas: dict[str, Temporada] = {}
    festivo_local_usado: tuple[str, str] | None = None
    # (hora_salida, hora_llegada, parada_origen, parada_destino) -> salida provisional
    agrupadas: dict[tuple[time, time, str, str], _Acumulado] = {}

    for entrada in lineas:
        linea = entrada.linea
        temporada = calendario_servicio.temporada_de(linea, fecha)
        if temporada is None:
            continue
        temporadas_usadas[linea.id] = temporada

        if fecha.month in linea.meses_no_circula:
            continue

        clase, festivo_local = calendario_servicio.clase_dia_linea(
            info, horarios.festivos_por_linea.get(linea.id, {})
        )
        if festivo_local is not None and festivo_local_usado is None:
            festivo_local_usado = festivo_local

        estado = linea.dias.get(temporada.nombre, {}).get(clase)
        if estado is None or estado == "sin_servicio":
            continue
        if estado == "sin_datos":
            lineas_sin_datos.add(linea.id)
            continue

        # estado == "horario"
        for tramo in entrada.por_temporada.get(temporada.nombre, ()):
            if clase not in tramo.clases:
                continue
            # `clase` es la de ESTA línea: un festivo local la vuelve
            # "festivos" aunque el día sea viernes lectivo.
            if tramo.solo_viernes_lectivo and not (
                info.dia_semana == "viernes" and info.es_lectivo and clase == "viernes"
            ):
                continue
            clave = (
                tramo.hora_salida,
                tramo.hora_llegada,
                tramo.parada_origen,
                tramo.parada_destino,
            )
            acumulado = agrupadas.setdefault(clave, _Acumulado(tramo))
            if linea.id not in acumulado.lineas:
                acumulado.lineas.append(linea.id)
            for nota in tramo.notas:
                if nota not in acumulado.notas:
                    acumulado.notas.append(nota)

    salidas = [
        Salida(
            hora_salida=e.tramo.hora_salida,
            hora_llegada=e.tramo.hora_llegada,
            duracion_min=minutes_of(e.tramo.hora_llegada) - minutes_of(e.tramo.hora_salida),
            parada_origen=e.tramo.parada_origen,
            parada_destino=e.tramo.parada_destino,
            lineas=tuple(e.lineas),
            notas=tuple(e.notas),
        )
        for e in agrupadas.values()
    ]
    salidas.sort(key=lambda s: s.hora_salida)

    if salidas:
        estado_final: EstadoConsulta = "con_salidas"
    elif lineas_sin_datos:
        estado_final = "sin_datos"
    else:
        estado_final = "sin_servicio"

    temporadas = tuple(sorted(temporadas_usadas.items(), key=lambda item: item[0]))
    return _Resolucion(
        estado_final,
        salidas,
        info,
        temporadas,
        tuple(sorted(lineas_sin_datos)),
        False,
        festivo_local=festivo_local_usado,
    )


def es_no_vendible(horarios: Horarios, a: str, b: str) -> bool:
    """True si la empresa no vende billetes entre `a` y `b`, en ninguno de
    los dos sentidos . Único sitio que consulta `modelo.no_vendibles`."""
    return frozenset((a, b)) in horarios.modelo.no_vendibles


def consultar(
    horarios: Horarios,
    origen: str,
    destino: str,
    fecha: date,
    ahora: datetime | None = None,
    dias_siguiente: int = SIGUIENTE_CON_SERVICIO_DIAS,
) -> Consulta:
    """`dias_siguiente`: ventana en la que se busca el siguiente día con
    salidas (`next_day_search_days` de la config del pack)."""
    modelo = horarios.modelo
    if origen == destino:
        raise ValueError("origen y destino no pueden ser la misma localidad")
    if origen not in modelo.localidades:
        raise ValueError(f"localidad de origen sin definir: '{origen}'")
    if destino not in modelo.localidades:
        raise ValueError(f"localidad de destino sin definir: '{destino}'")
    if modelo.localidades[origen].pendiente is not None:
        raise ValueError(f"localidad de origen pendiente, sin horas: '{origen}'")
    if modelo.localidades[destino].pendiente is not None:
        raise ValueError(f"localidad de destino pendiente, sin horas: '{destino}'")

    if es_no_vendible(horarios, origen, destino):
        return Consulta(
            estado="no_vendible",
            salidas=(),
            info_dia=None,
            temporadas=(),
            lineas_sin_datos=(),
            fuera_de_calendario=False,
            siguiente_con_servicio=None,
        )

    resolucion = _resolver_fecha(horarios, origen, destino, fecha)
    estado = resolucion.estado
    salidas = resolucion.salidas
    info = resolucion.info
    temporadas = resolucion.temporadas
    lineas_sin_datos = resolucion.lineas_sin_datos
    fuera_de_calendario = resolucion.fuera_de_calendario

    if ahora is not None and ahora.date() == fecha:
        hora_actual = ahora.time()
        salidas = [
            Salida(
                hora_salida=s.hora_salida,
                hora_llegada=s.hora_llegada,
                duracion_min=s.duracion_min,
                parada_origen=s.parada_origen,
                parada_destino=s.parada_destino,
                lineas=s.lineas,
                notas=s.notas,
                ya_salio=s.hora_salida < hora_actual,
            )
            for s in salidas
        ]

    siguiente_con_servicio: date | None = None
    if not salidas and estado != "sin_trayecto" and not fuera_de_calendario:
        calendario = modelo.calendario
        assert calendario is not None
        for delta in range(1, dias_siguiente + 1):
            candidata = fecha + timedelta(days=delta)
            if candidata > calendario.vigencia_fin:
                break
            if _resolver_fecha(horarios, origen, destino, candidata).salidas:
                siguiente_con_servicio = candidata
                break

    return Consulta(
        estado=estado,
        salidas=tuple(salidas),
        info_dia=info,
        temporadas=temporadas,
        lineas_sin_datos=lineas_sin_datos,
        fuera_de_calendario=fuera_de_calendario,
        siguiente_con_servicio=siguiente_con_servicio,
        sin_servicio_general=resolucion.sin_servicio_general,
        festivo_local=resolucion.festivo_local,
    )


def destinos_desde(horarios: Horarios, origen: str, linea: str | None = None) -> frozenset[str]:
    """Localidades a las que se llega en servicio directo desde `origen`, en
    cualquier temporada/día (no filtrado por fecha). Nunca incluye `origen` ni
    los destinos no vendibles desde él . Con `linea`, solo cuenta los
    viajes de esa línea (id)."""
    resultado: set[str] = set()
    for viaje in horarios.localidad_viajes.get(origen, ()):
        if linea is not None and viaje.linea != linea:
            continue
        localidades_viaje = _localidades_del_viaje(horarios, viaje)
        if origen not in localidades_viaje:
            continue
        idx_primero = localidades_viaje.index(origen)
        for loc in localidades_viaje[idx_primero + 1 :]:
            if loc is not None and loc != origen:
                resultado.add(loc)
    return frozenset(loc for loc in resultado if not es_no_vendible(horarios, origen, loc))
