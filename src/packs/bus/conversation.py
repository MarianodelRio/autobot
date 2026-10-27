"""packs/bus/conversation.py — máquina de estados de la conversación.

Cambia el pegamento: en vez de enviar por WhatsApp, cada paso añade respuestas
a un `_Turno`, y el estado es un dict JSON que guarda el runtime. El candado
por contacto, la caducidad (30 min), los comandos globales (`menu`, `baja`…),
la recuperación ante errores y los comandos de administrador son de la
plataforma. El reloj es `ctx.clock`, en la zona del
tenant.

Estado: `step` (uno de los estados de abajo; sin `step`, MENU), `campo`
("origen" | "destino" mientras se busca o confirma), `origen`, `destino`,
`fecha` (ISO) y `pendiente` (id de localidad por confirmar).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import date, datetime, timedelta
from typing import Any

from core.actions import Action, RecordMetric
from core.messages import IncomingMessage
from core.pack import PackContext, PackResult
from core.replies import Reply, Text
from core.ui import PER_PAGE
from packs.bus import fechas, formato, query
from packs.bus import messages as msg
from packs.bus.config import BusConfig
from packs.bus.datos import Datos
from packs.bus.interactive import (
    build_candidatas,
    build_confirmar,
    build_destinos,
    build_dias,
    build_escribir,
    build_info,
    build_linea,
    build_lineas,
    build_localidad_pendiente,
    build_menu,
    build_origen,
    build_resultado,
)
from packs.bus.matcher import lineas as matcher_lineas
from packs.bus.modelo import Linea, Localidad

# Textos no reconocidos se registran normalizados, nunca con el identificador
# del contacto: si el texto contiene 6 dígitos o más (p. ej.
# un teléfono escrito donde iba una fecha, con o sin espacios/guiones), se
# registra `<numero>` en su lugar. El recuento se hace sobre los dígitos del
# texto sin separadores, porque `formato.normalizar()` sustituye separadores
# por espacios y los dígitos dejarían de estar consecutivos.
_RE_NO_DIGITO = re.compile(r"\D")

# Palabras que, escritas en cualquier estado, vuelven al menú. `menu`, `menú` e
# `inicio` ya los atiende la plataforma (llegan como texto vacío); `hola` y
# `salir` son propias del pack.
_ESCAPE_MENU = {"menu", "menú", "inicio", "hola", "salir"}


def _texto_para_log(texto: str) -> str:
    normalizado = formato.normalizar(texto)[:40]
    solo_digitos = _RE_NO_DIGITO.sub("", normalizado)
    if len(solo_digitos) >= 6:
        return "<numero>"
    return normalizado


# ── Estados ────────────────────────────────────────────────────────────────
MENU = "MENU"
SEL_ORIGEN = "SEL_ORIGEN"
ESCRIBIR_ORIGEN = "ESCRIBIR_ORIGEN"
SEL_DESTINO = "SEL_DESTINO"
ESCRIBIR_DESTINO = "ESCRIBIR_DESTINO"
CONFIRMAR_PUEBLO = "CONFIRMAR_PUEBLO"
SEL_DIA = "SEL_DIA"
ESCRIBIR_FECHA = "ESCRIBIR_FECHA"
RESULTADO = "RESULTADO"


class _Turno:
    """Lo que el pack sabe y responde en un mensaje: config, datos, reloj,
    estado (mutable, se devuelve entero) y respuestas acumuladas."""

    def __init__(self, ctx: PackContext) -> None:
        cfg, datos = ctx.config, ctx.data
        assert isinstance(cfg, BusConfig) and isinstance(datos, Datos)
        self.ctx = ctx
        self.cfg = cfg
        self.datos = datos
        self.estado: dict[str, Any] = dict(ctx.state)
        self.replies: list[Reply] = []
        self.actions: list[Action] = []

    def responder(self, *replies: Reply) -> None:
        self.replies.extend(replies)

    def ahora(self) -> datetime:
        return self.ctx.clock.now()

    def hoy(self) -> date:
        return self.ahora().date()

    @property
    def step(self) -> str:
        return str(self.estado.get("step", MENU))

    @step.setter
    def step(self, valor: str) -> None:
        self.estado["step"] = valor

    def get(self, clave: str) -> str | None:
        valor = self.estado.get(clave)
        return valor if isinstance(valor, str) else None

    def set(self, clave: str, valor: str | None) -> None:
        if valor is None:
            self.estado.pop(clave, None)
        else:
            self.estado[clave] = valor

    @property
    def origen(self) -> str:
        """Solo en los pasos que ya tienen origen; un estado sin él es un
        error de programación (o un estado manipulado: se vuelve al menú)."""
        origen = self.get("origen")
        if origen is None or origen not in self.datos.horarios.modelo.localidades:
            raise _EstadoInvalido
        return origen

    @property
    def destino(self) -> str:
        destino = self.get("destino")
        if destino is None or destino not in self.datos.horarios.modelo.localidades:
            raise _EstadoInvalido
        return destino


class _EstadoInvalido(Exception):
    """El estado guardado no tiene lo que el paso necesita."""


# ── Helpers puros ───────────────────────────────────────────────────────


def ordenar_destinos(
    alcanzables: list[str], prioridad: list[str], nombres: dict[str, str]
) -> list[tuple[str, str]]:
    """Orden de negocio primero (según `start_menu_towns`), después el
    resto en orden alfabético."""
    prioridad_presentes = [lid for lid in prioridad if lid in alcanzables]
    resto = [lid for lid in alcanzables if lid not in prioridad_presentes]
    resto.sort(key=lambda lid: formato.normalizar(nombres[lid]))
    orden = prioridad_presentes + resto
    return [(lid, nombres[lid]) for lid in orden]


def _nombres(datos: Datos, ids: tuple[str, ...]) -> list[tuple[str, str]]:
    return [(lid, datos.horarios.modelo.localidades[lid].nombre) for lid in ids]


def _nombre_localidad(datos: Datos, lid: str) -> str:
    return datos.horarios.modelo.localidades[lid].nombre


def _consultar(t: _Turno, origen: str, destino: str, fecha: date) -> query.Consulta:
    return query.consultar(
        t.datos.horarios,
        origen,
        destino,
        fecha,
        ahora=t.ahora(),
        dias_siguiente=t.cfg.next_day_search_days,
    )


# ── Navegación ──────────────────────────────────────────────────────────


def to_menu(t: _Turno) -> None:
    t.estado = {}
    t.responder(build_menu(t.cfg))


def _ir_a_origen(t: _Turno, aviso: str | None = None) -> None:
    t.estado = {"step": SEL_ORIGEN, "campo": "origen"}
    localidades = _nombres(t.datos, t.datos.menu_origen)
    t.responder(build_origen(t.cfg, localidades, aviso=aviso))


def _mostrar_paso(
    t: _Turno, campo: str, aviso: str | None = None, con_lineas: bool = False
) -> None:
    datos = t.datos
    if campo == "origen":
        localidades = _nombres(datos, datos.menu_origen)
        t.responder(build_origen(t.cfg, localidades, aviso=aviso, con_lineas=con_lineas))
    else:
        origen = t.origen
        alcanzables = list(query.destinos_desde(datos.horarios, origen))
        nombres_map = {lid: _nombre_localidad(datos, lid) for lid in alcanzables}
        ordenados = ordenar_destinos(alcanzables, list(datos.menu_origen), nombres_map)
        t.responder(
            build_destinos(
                t.cfg,
                _nombre_localidad(datos, origen),
                ordenados,
                aviso=aviso,
                con_lineas=con_lineas,
            )
        )


# ── Búsqueda de texto libre ─────────────────────────────


def _buscar(t: _Turno, campo: str, texto: str) -> None:
    datos = t.datos
    coincidencia = datos.matcher.buscar(texto)

    if coincidencia.tipo == "unico":
        _elegir(t, campo, coincidencia.localidades[0])
        return

    if coincidencia.tipo == "confirmar":
        pendiente = coincidencia.localidades[0]
        t.set("pendiente", pendiente)
        t.set("campo", campo)
        t.step = CONFIRMAR_PUEBLO
        t.responder(build_confirmar(t.cfg, _nombre_localidad(datos, pendiente)))
        return

    if coincidencia.tipo == "elegir":
        t.set("campo", campo)
        t.responder(build_candidatas(t.cfg, _nombres(datos, coincidencia.localidades)))
        return

    if coincidencia.tipo == "demasiadas":
        t.set("campo", campo)
        t.responder(build_escribir(t.cfg, campo, msg.msg_demasiadas_coincidencias()))
        return

    # sin_coincidencia
    t.ctx.log.info("[NO_RECONOCIDO] paso=%s texto=%s", campo, _texto_para_log(texto))
    t.set("campo", campo)
    _mostrar_paso(t, campo, aviso=msg.msg_no_conozco_ese_pueblo(), con_lineas=True)


def _elegir(t: _Turno, campo: str, localidad_id: str) -> None:
    datos = t.datos
    loc = datos.horarios.modelo.localidades.get(localidad_id)
    if loc is not None and loc.pendiente is not None:
        assert loc.ver is not None  # el validador exige `ver` en toda localidad pendiente
        # Aldea sin hora de paso (P15/P32): se ofrece consultar `ver` en su
        # lugar; no se toca el origen ni se emite "sin trayecto".
        t.step = SEL_ORIGEN if campo == "origen" else SEL_DESTINO
        t.set("campo", campo)
        t.set("pendiente", None)
        ver_nombre = _nombre_localidad(datos, loc.ver)
        t.responder(
            build_localidad_pendiente(
                t.cfg,
                msg.msg_localidad_pendiente(loc.nombre, ver_nombre, loc.minutos or 0),
                loc.ver,
                ver_nombre,
            )
        )
        return
    if loc is None:
        # Id manipulado (o de una versión anterior del dataset): se repite el paso.
        _mostrar_paso(t, campo)
        return
    if campo == "origen":
        destinos = query.destinos_desde(datos.horarios, localidad_id)
        if not destinos:
            nombre = _nombre_localidad(datos, localidad_id)
            _mostrar_paso(t, "origen", aviso=msg.msg_sin_destinos_desde_origen(t.cfg, nombre))
            return
        t.set("origen", localidad_id)
        t.set("destino", None)
        t.set("campo", "destino")
        t.step = SEL_DESTINO
        _mostrar_paso(t, "destino")
        return

    # campo == "destino"
    origen = t.origen
    if localidad_id == origen:
        _mostrar_paso(t, "destino", aviso=msg.msg_destino_distinto())
        return
    alcanzables = query.destinos_desde(datos.horarios, origen)
    if localidad_id not in alcanzables:
        origen_nombre = _nombre_localidad(datos, origen)
        destino_nombre = _nombre_localidad(datos, localidad_id)
        if query.es_no_vendible(datos.horarios, origen, localidad_id):
            aviso = msg.msg_no_vendible(origen_nombre, destino_nombre)
        else:
            aviso = msg.msg_sin_trayecto(t.cfg, origen_nombre, destino_nombre)
        _mostrar_paso(t, "destino", aviso=aviso)
        return
    t.set("destino", localidad_id)
    t.set("campo", None)
    _mostrar_dias(t)


def _usar(t: _Turno, campo: str, value: str) -> None:
    """Botón `usar:<id>` del mensaje de localidad pendiente. El id puede venir
    manipulado: si no existe o es pendiente, se repite el paso sin cambios."""
    lid = value.removeprefix("usar:")
    loc = t.datos.horarios.modelo.localidades.get(lid)
    if loc is None or loc.pendiente is not None:
        _mostrar_paso(t, campo)
        return
    _elegir(t, campo, lid)


# ── Pueblos por línea (P18) ───────────────────────────────────────────


def _lineas_visibles(
    datos: Datos, campo: str, origen: str | None
) -> list[tuple[Linea, tuple[Localidad, ...]]]:
    """[(Linea, pueblos)] que ve el cliente. Origen: todas las líneas. Destino:
    de cada línea solo los pueblos alcanzables desde `origen` en esa línea,
    descartando las líneas que se quedan sin ninguno."""
    todas = matcher_lineas(datos.horarios)
    if campo != "destino" or origen is None:
        return list(todas)
    resultado = []
    for linea, locs in todas:
        alcanzables = query.destinos_desde(datos.horarios, origen, linea.id)
        visibles = tuple(loc for loc in locs if loc.id in alcanzables)
        if visibles:
            resultado.append((linea, visibles))
    return resultado


def _n_paginas(n: int) -> int:
    return max(1, -(-n // PER_PAGE))


def _origen_para_lineas(t: _Turno, campo: str) -> str | None:
    return t.origen if campo == "destino" else None


def _mostrar_lineas(t: _Turno, campo: str, pagina: int = 0) -> None:
    visibles = _lineas_visibles(t.datos, campo, _origen_para_lineas(t, campo))
    if not visibles:
        t.set("campo", campo)
        _mostrar_paso(t, campo, aviso=msg.msg_sin_lineas())
        return
    if pagina < 0 or pagina >= _n_paginas(len(visibles)):
        pagina = 0
    filas = [(linea, len(locs)) for linea, locs in visibles]
    t.set("campo", campo)
    t.responder(build_lineas(t.cfg, filas, pagina, campo))


def _pagina_de_lineas(value: str) -> int:
    try:
        return int(value.split(":", 1)[1])
    except ValueError, IndexError:
        return 0


def _mostrar_linea_pagina(t: _Turno, campo: str, value: str) -> None:
    partes = value.split(":")
    if len(partes) != 3:
        _mostrar_lineas(t, campo, 0)
        return
    lid, pag_txt = partes[1], partes[2]
    try:
        pagina = int(pag_txt)
    except ValueError:
        _mostrar_lineas(t, campo, 0)
        return
    elegida = next(
        (
            (linea, locs)
            for linea, locs in _lineas_visibles(t.datos, campo, _origen_para_lineas(t, campo))
            if linea.id == lid
        ),
        None,
    )
    if elegida is None:
        _mostrar_lineas(t, campo, 0)
        return
    linea, locs = elegida
    # Una página inexistente vuelve a la lista de líneas
    # (`core.ui.paginate` mostraría la primera página de la línea).
    if pagina < 0 or pagina >= _n_paginas(len(locs)):
        _mostrar_lineas(t, campo, 0)
        return
    t.set("campo", campo)
    t.responder(build_linea(t.cfg, linea, [(loc.id, loc.nombre) for loc in locs], pagina))


# ── Día ────────────────────────────────────────────────────────────────


def _titulo_dia(fecha: date, indice: int) -> str:
    abrev = msg.nombre_dia_abrev_es(fecha)
    dd_mm = f"{fecha.day:02d}/{fecha.month:02d}"
    if indice == 0:
        return f"Hoy · {abrev} {dd_mm}"
    if indice == 1:
        return f"Mañana · {abrev} {dd_mm}"
    return f"{abrev.capitalize()} {dd_mm}"


def _descripcion_dia(consulta: query.Consulta, es_hoy: bool) -> str:
    """Descripción de una fila de la lista de días."""
    es_festivo = (
        consulta.info_dia is not None and consulta.info_dia.es_festivo
    ) or consulta.festivo_local is not None
    prefijo = "festivo · " if es_festivo else ""
    sufijo = " · puede haber más" if consulta.lineas_sin_datos else ""

    if consulta.estado == "con_salidas":
        n = len(consulta.salidas)
        if es_hoy:
            pendientes = [s for s in consulta.salidas if not s.ya_salio]
            if not pendientes:
                return prefijo + "ya no quedan salidas hoy" + sufijo
            proxima = pendientes[0].hora_salida.strftime("%H:%M")
            return prefijo + f"{n} salidas · próxima {proxima}" + sufijo
        if n == 1:
            hora = consulta.salidas[0].hora_salida.strftime("%H:%M")
            return prefijo + f"1 salida · {hora}" + sufijo
        primera = consulta.salidas[0].hora_salida.strftime("%H:%M")
        ultima = consulta.salidas[-1].hora_salida.strftime("%H:%M")
        return prefijo + f"{n} salidas · de {primera} a {ultima}" + sufijo
    if consulta.estado == "sin_servicio":
        return prefijo + "sin servicio"  # también sin_servicio_general (P03g)
    if consulta.estado == "sin_datos":
        return prefijo + "horario no disponible"
    if consulta.estado == "no_vendible":
        return "no vendemos este trayecto"  # defensivo: no debería llegar aquí
    return prefijo + "—"


def _mostrar_dias(t: _Turno, aviso: str | None = None) -> None:
    origen, destino = t.origen, t.destino
    hoy = t.hoy()
    filas = []
    for i in range(7):
        f = hoy + timedelta(days=i)
        consulta = _consultar(t, origen, destino, f)
        filas.append(
            (f"dia:{f.isoformat()}", _titulo_dia(f, i), _descripcion_dia(consulta, es_hoy=(i == 0)))
        )
    t.step = SEL_DIA
    t.set("campo", None)
    t.responder(
        build_dias(
            t.cfg,
            _nombre_localidad(t.datos, origen),
            _nombre_localidad(t.datos, destino),
            filas,
            aviso=aviso,
        )
    )


# ── Fecha libre ────────────────────────────────────────────────────────


def _leer_fecha_libre(t: _Turno, texto: str, en_lista: bool) -> None:
    lectura = fechas.leer_fecha(texto, t.hoy())
    if lectura.estado == "ok" and lectura.fecha is not None:
        _resultado(t, lectura.fecha)
        return
    if lectura.estado == "pasada":
        if en_lista:
            _mostrar_dias(t, aviso=msg.msg_fecha_pasada())
        else:
            t.responder(Text(msg.msg_fecha_pasada_con_formato()))
        return
    # formato | inexistente
    t.ctx.log.info("[NO_RECONOCIDO] paso=fecha texto=%s", _texto_para_log(texto))
    if en_lista:
        _mostrar_dias(t, aviso=msg.msg_elige_de_la_lista())
    else:
        t.responder(Text(msg.msg_fecha_no_entendida()))


# ── Resultado ──────────────────────────────────────────────────────────


def _botones_resultado(t: _Turno, consulta: query.Consulta, fecha: date) -> list[tuple[str, str]]:
    hoy = t.hoy()
    calendario = t.datos.horarios.modelo.calendario
    assert calendario is not None
    vigencia_fin = calendario.vigencia_fin
    botones: list[tuple[str, str]] = []

    if consulta.estado == "no_vendible":
        # defensivo: sin "otro día" ni "vuelta" (tampoco se vende la vuelta)
        return [("otra_consulta", "🔍 Otra consulta")]

    if consulta.estado == "con_salidas":
        pendientes = [s for s in consulta.salidas if not s.ya_salio]
        if not pendientes and fecha == hoy:
            manana = fecha + timedelta(days=1)
            if manana <= vigencia_fin:
                botones.append((f"dia:{manana.isoformat()}", "📅 Mañana"))
            else:
                botones.append(("otro_dia", "📅 Otro día"))
        else:
            botones.append(("otro_dia", "📅 Otro día"))
    elif consulta.estado == "sin_servicio" and consulta.siguiente_con_servicio:
        sig = consulta.siguiente_con_servicio
        botones.append((f"dia:{sig.isoformat()}", f"📅 Día {sig.day}/{sig.month}"))
    else:
        botones.append(("otro_dia", "📅 Otro día"))

    botones.append(("vuelta", "🔄 Ver la vuelta"))
    botones.append(("otra_consulta", "🔍 Otra consulta"))
    return botones[:3]


def _resultado(t: _Turno, fecha: date) -> None:
    origen, destino = t.origen, t.destino
    consulta = _consultar(t, origen, destino, fecha)
    texto = msg.msg_resultado(
        t.cfg,
        consulta,
        t.datos.horarios,
        _nombre_localidad(t.datos, origen),
        _nombre_localidad(t.datos, destino),
        fecha,
    )
    botones = _botones_resultado(t, consulta, fecha)
    t.set("fecha", fecha.isoformat())
    t.step = RESULTADO
    t.responder(*build_resultado(t.cfg, texto, botones))
    if consulta.estado == "con_salidas":
        t.actions.append(RecordMetric("schedule_query", t.ctx.idem.event("metric:schedule_query")))


# ── Handlers por estado ───────────────────────────────────────────────


def _handle_menu(t: _Turno, value: str) -> None:
    if value == "menu_horarios":
        _ir_a_origen(t)
    elif value == "menu_info":
        t.responder(build_info(t.cfg))
    else:
        to_menu(t)


def _handle_sel_origen(t: _Turno, value: str) -> None:
    if value.startswith("loc:"):
        _elegir(t, "origen", value.removeprefix("loc:"))
    elif value.startswith("usar:"):
        _usar(t, "origen", value)
    elif value == "escribir":
        t.step = ESCRIBIR_ORIGEN
        t.set("campo", "origen")
        t.responder(build_escribir(t.cfg, "origen", msg.msg_pedir_pueblo("origen")))
    elif value.startswith("lineas:"):
        _mostrar_lineas(t, "origen", _pagina_de_lineas(value))
    elif value.startswith("linea:"):
        _mostrar_linea_pagina(t, "origen", value)
    elif value == "zonas" or value.startswith("zona:"):
        # Botones y filas antiguos (antes de P18): lista de líneas.
        _mostrar_lineas(t, "origen", 0)
    elif value == "menu":
        to_menu(t)
    else:
        _buscar(t, "origen", value)


def _handle_sel_destino(t: _Turno, value: str) -> None:
    if value.startswith("loc:"):
        _elegir(t, "destino", value.removeprefix("loc:"))
    elif value.startswith("usar:"):
        _usar(t, "destino", value)
    elif value == "escribir":
        t.step = ESCRIBIR_DESTINO
        t.set("campo", "destino")
        t.responder(build_escribir(t.cfg, "destino", msg.msg_pedir_pueblo("destino")))
    elif value.startswith("lineas:"):
        _mostrar_lineas(t, "destino", _pagina_de_lineas(value))
    elif value.startswith("linea:"):
        _mostrar_linea_pagina(t, "destino", value)
    elif value == "zonas" or value.startswith("zona:"):
        # Botones y filas antiguos (antes de P18): lista de líneas.
        _mostrar_lineas(t, "destino", 0)
    elif value == "cambiar_origen":
        _ir_a_origen(t)
    else:
        _buscar(t, "destino", value)


def _handle_confirmar_pueblo(t: _Turno, value: str) -> None:
    campo = t.get("campo")
    if value == "si":
        pendiente = t.get("pendiente")
        if pendiente is None or campo is None:
            to_menu(t)
            return
        t.set("pendiente", None)
        _elegir(t, campo, pendiente)
    elif value == "no":
        t.set("pendiente", None)
        campo = campo or "origen"
        t.step = ESCRIBIR_ORIGEN if campo == "origen" else ESCRIBIR_DESTINO
        t.responder(build_escribir(t.cfg, campo, msg.msg_escribelo_de_otra_forma()))
    else:
        _buscar(t, campo or "origen", value)


def _fecha_de(value: str) -> date | None:
    try:
        return date.fromisoformat(value.removeprefix("dia:"))
    except ValueError:
        return None


def _handle_sel_dia(t: _Turno, value: str) -> None:
    if value.startswith("dia:"):
        f = _fecha_de(value)
        if f is None:
            _mostrar_dias(t)
            return
        _resultado(t, f)
    elif value == "otra_fecha":
        t.step = ESCRIBIR_FECHA
        t.responder(Text(msg.msg_formato_fecha()))
    else:
        _leer_fecha_libre(t, value, en_lista=True)


def _handle_escribir_fecha(t: _Turno, value: str) -> None:
    _leer_fecha_libre(t, value, en_lista=False)


def _handle_resultado(t: _Turno, value: str) -> None:
    datos = t.datos
    if value == "otro_dia":
        _mostrar_dias(t)
    elif value == "vuelta":
        nuevo_origen, nuevo_destino = t.destino, t.origen
        alcanzables = query.destinos_desde(datos.horarios, nuevo_origen)
        if nuevo_destino not in alcanzables:
            origen_nombre = _nombre_localidad(datos, nuevo_origen)
            destino_nombre = _nombre_localidad(datos, nuevo_destino)
            if query.es_no_vendible(datos.horarios, nuevo_origen, nuevo_destino):
                texto = msg.msg_no_vendible(origen_nombre, destino_nombre)
            else:
                texto = msg.msg_sin_trayecto(t.cfg, origen_nombre, destino_nombre)
            t.responder(Text(texto))
            to_menu(t)
            return
        t.set("origen", nuevo_origen)
        t.set("destino", nuevo_destino)
        _mostrar_dias(t)
    elif value == "otra_consulta":
        _ir_a_origen(t)
    elif value.startswith("dia:"):
        f = _fecha_de(value)
        if f is None:
            to_menu(t)
            return
        _resultado(t, f)
    else:
        to_menu(t)


DESPACHO: dict[str, Callable[[_Turno, str], None]] = {
    MENU: _handle_menu,
    SEL_ORIGEN: _handle_sel_origen,
    ESCRIBIR_ORIGEN: _handle_sel_origen,
    SEL_DESTINO: _handle_sel_destino,
    ESCRIBIR_DESTINO: _handle_sel_destino,
    CONFIRMAR_PUEBLO: _handle_confirmar_pueblo,
    SEL_DIA: _handle_sel_dia,
    ESCRIBIR_FECHA: _handle_escribir_fecha,
    RESULTADO: _handle_resultado,
}


# ── Punto de entrada (Pack.handle_message) ─────────────────────────────


def handle(ctx: PackContext, message: IncomingMessage) -> PackResult:
    t = _Turno(ctx)

    if message.type == "unsupported":
        t.responder(Text(msg.msg_input_no_soportado()))
        return PackResult(replies=t.replies)

    text = message.text if message.type == "text" else None
    interactive_id = message.payload if message.type == "button" else None
    value = interactive_id if interactive_id is not None else (text or "")

    try:
        _despachar(t, text, interactive_id, value)
    except _EstadoInvalido:
        # Estado guardado incompleto o con ids que ya no existen (p. ej. tras
        # cambiar el dataset): se vuelve al menú en vez de fallar.
        t.replies.clear()
        to_menu(t)
    return PackResult(replies=t.replies, state=t.estado, actions=t.actions)


def _despachar(t: _Turno, text: str | None, interactive_id: str | None, value: str) -> None:
    # Escape global: palabras que vuelven al menú desde cualquier estado.
    if text is not None and text.strip().lower() in _ESCAPE_MENU:
        to_menu(t)
        return

    # Globales: disponibles desde cualquier estado.
    if interactive_id == "menu":
        to_menu(t)
        return
    if interactive_id in ("otra_consulta", "menu_horarios"):
        _ir_a_origen(t)
        return

    handler = DESPACHO.get(t.step)
    if handler is None:
        to_menu(t)
        return
    handler(t, value)
