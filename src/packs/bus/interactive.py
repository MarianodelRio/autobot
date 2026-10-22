"""packs/bus/interactive.py — constructores de las respuestas interactivas
(listas y botones) del pack, portados de `buscaBus/app/utils/interactive.py`.

Construyen `core.replies` con los helpers de `core.ui`, que truncan títulos como
el origen y validan los límites comunes (design.md §6.1). Son PUROS: no leen
estado ni el reloj; reciben ya calculado lo que pintan. El pie de los mensajes
lleva el nombre del negocio de la config (buscaBus lo tenía fijo).
"""

from __future__ import annotations

import re

from core.limits import (
    MAX_BUTTON_TITLE,
    MAX_FOOTER,
    MAX_HEADER,
    MAX_INTERACTIVE_BODY,
    MAX_LIST_ROWS,
    MAX_ROW_DESCRIPTION,
)
from core.limits import MAX_ROW_TITLE as MAX_TITULO_FILA
from core.replies import Buttons, List, Reply, Row, Text
from core.ui import button, buttons_msg, list_msg, paginate, row, section, trunc
from packs.bus import messages as msg
from packs.bus.config import BusConfig
from packs.bus.modelo import Linea


def _pie(cfg: BusConfig) -> str:
    return trunc(f"{cfg.business_name} · Horarios de autobús", MAX_FOOTER)


def _cabecera(texto: str) -> str:
    return trunc(texto, MAX_HEADER)


def _fila_localidad(id_: str, nombre: str) -> Row:
    """Fila para una localidad: la descripción lleva el nombre completo si el
    título se truncó (buscaBus, plan fase 4, paso 10)."""
    descripcion = nombre if len(nombre) > MAX_TITULO_FILA else None
    return row(id_, nombre, descripcion)


def _con_aviso(body: str, aviso: str | None) -> str:
    return f"{aviso}\n\n{body}" if aviso else body


# ── Menú / información ──────────────────────────────────────────────────


def build_menu(cfg: BusConfig) -> Buttons:
    return buttons_msg(
        header=_cabecera(f"🚌 {cfg.business_name} · Horarios"),
        body=f"¿Qué necesitas?\n\n{msg.msg_menu_footer(cfg)}",
        buttons=[
            button("menu_horarios", "🚌 Ver horarios"),
            button("menu_info", "ℹ️ Contacto"),
        ],
        footer=_pie(cfg),
    )


def build_info(cfg: BusConfig) -> Buttons:
    return buttons_msg(
        body=msg.msg_info(cfg),
        buttons=[
            button("menu_horarios", "🚌 Ver horarios"),
            button("menu", "↩️ Menú"),
        ],
        footer=_pie(cfg),
    )


# ── Origen / destino ──────────────────────────────────────────────────────


def build_origen(
    cfg: BusConfig,
    localidades: list[tuple[str, str]],
    aviso: str | None = None,
    con_lineas: bool = False,
) -> List:
    """localidades: lista de (id, nombre) ya recortada a como mucho 8."""
    rows = [_fila_localidad(f"loc:{lid}", nombre) for lid, nombre in localidades[:8]]
    if con_lineas:
        rows.append(row("lineas:0", "🚌 Ver pueblos por línea"))
    else:
        rows.append(row("escribir", "✍️ Otro pueblo"))
    rows.append(row("menu", "↩️ Volver al menú"))
    return list_msg(
        header="🚌 Horarios de autobús",
        body=_con_aviso("¿Desde qué pueblo sales?", aviso),
        button_label="Ver pueblos",
        sections=[section("Pueblos", rows)],
        footer=_pie(cfg),
    )


def build_destinos(
    cfg: BusConfig,
    origen_nombre: str,
    destinos_ordenados: list[tuple[str, str]],
    aviso: str | None = None,
    con_lineas: bool = False,
) -> List:
    """destinos_ordenados: lista completa de (id, nombre) ya ordenada
    (`conversation.ordenar_destinos`). Si hay 9 o menos, se muestran todos +
    volver (cero ambigüedad, design.md §10.3). Si hay más, se muestran los 8
    primeros + fila de escribir/líneas + volver = 10 filas."""
    if len(destinos_ordenados) <= MAX_LIST_ROWS - 1:
        rows = [_fila_localidad(f"loc:{lid}", nombre) for lid, nombre in destinos_ordenados]
    else:
        rows = [_fila_localidad(f"loc:{lid}", nombre) for lid, nombre in destinos_ordenados[:8]]
        if con_lineas:
            rows.append(row("lineas:0", "🚌 Ver pueblos por línea"))
        else:
            rows.append(row("escribir", "✍️ Otro destino"))
    rows.append(row("cambiar_origen", "↩️ Cambiar origen"))
    return list_msg(
        header=_cabecera(f"🚌 Desde {origen_nombre}"),
        body=_con_aviso("¿A dónde vas?", aviso),
        button_label="Ver destinos",
        sections=[section("Destinos", rows)],
        footer=_pie(cfg),
    )


def build_candidatas(cfg: BusConfig, localidades: list[tuple[str, str]]) -> Buttons | List:
    """2-9 candidatas. 2-3 con nombres cortos -> botones; si no, lista."""
    if 2 <= len(localidades) <= 3 and all(len(n) <= MAX_BUTTON_TITLE for _, n in localidades):
        return buttons_msg(
            body="¿Cuál de estos es?",
            buttons=[button(f"loc:{lid}", nombre) for lid, nombre in localidades],
            footer=_pie(cfg),
        )
    rows = [_fila_localidad(f"loc:{lid}", nombre) for lid, nombre in localidades[:9]]
    rows.append(row("menu", "↩️ Volver al menú"))
    return list_msg(
        body="¿Cuál de estos es?",
        button_label="Elegir",
        sections=[section("Coincidencias", rows)],
        footer=_pie(cfg),
    )


def build_confirmar(cfg: BusConfig, localidad_nombre: str) -> Buttons:
    return buttons_msg(
        body=msg.msg_confirmar_errata(localidad_nombre),
        buttons=[button("si", "Sí"), button("no", "No")],
        footer=_pie(cfg),
    )


def build_escribir(cfg: BusConfig, campo: str, texto: str) -> Buttons:
    boton_volver = "cambiar_origen" if campo == "destino" else "menu"
    titulo_volver = "↩️ Menú" if boton_volver == "menu" else "↩️ Cambiar origen"
    return buttons_msg(
        body=texto,
        buttons=[
            button("lineas:0", "🚌 Ver por línea"),
            button(boton_volver, titulo_volver),
        ],
        footer=_pie(cfg),
    )


# ── Localidad pendiente (P15/P32) ─────────────────────────────────────────


def _titulo_usar(nombre: str) -> str:
    """ "Usar {nombre}" en 20 caracteres como mucho: nombre completo; si no
    cabe, sin el complemento " de/del ..."; si no, la primera palabra; último
    recurso, truncar."""
    prefijo = "Usar "
    candidatos = [nombre]
    corte = re.split(r"\s+(?:de|del)\s+", nombre, maxsplit=1)[0]
    candidatos.append(corte)
    candidatos.append(nombre.split()[0] if nombre.split() else nombre)
    for c in candidatos:
        if len(prefijo + c) <= MAX_BUTTON_TITLE:
            return prefijo + c
    return trunc(prefijo + candidatos[-1], MAX_BUTTON_TITLE)


def build_localidad_pendiente(cfg: BusConfig, texto: str, ver_id: str, ver_nombre: str) -> Buttons:
    """Aldea sin hora de paso: ofrece consultar en su lugar la localidad `ver`
    o escribir otro pueblo. 2 botones."""
    return buttons_msg(
        body=texto,
        buttons=[
            button(f"usar:{ver_id}", _titulo_usar(ver_nombre)),
            button("escribir", "✍️ Otro pueblo"),
        ],
        footer=_pie(cfg),
    )


# ── Pueblos por línea (P18) ───────────────────────────────────────────


def descripcion_linea(linea: Linea, n_pueblos: int) -> str:
    """Descripción de la fila de una línea en la lista de líneas: "<nombre> ·
    N pueblos" si la línea tiene título corto (el nombre completo no cabe en el
    título de fila), o solo "N pueblos". Se recorta el nombre, nunca el
    recuento. Función pura, también la usa la vista de revisión."""
    cuenta = "1 pueblo" if n_pueblos == 1 else f"{n_pueblos} pueblos"
    if not linea.nombre_corto:
        return cuenta
    sufijo = f" · {cuenta}"
    nombre = linea.nombre
    if len(nombre) + len(sufijo) > MAX_ROW_DESCRIPTION:
        nombre = trunc(nombre, MAX_ROW_DESCRIPTION - len(sufijo) - 1) + "…"
    return nombre + sufijo


def build_lineas(cfg: BusConfig, lineas: list[tuple[Linea, int]], pagina: int, campo: str) -> List:
    """lineas: todas las (Linea, n_pueblos) visibles; `pagina` ya es una página
    válida. 8 + "Más líneas" + volver = 10 filas (`core.ui.paginate`)."""
    filas = [
        row(f"linea:{linea.id}:0", linea.titulo, descripcion_linea(linea, n)) for linea, n in lineas
    ]
    volver = (
        ("menu", "↩️ Volver al menú")
        if campo == "origen"
        else (
            "cambiar_origen",
            "↩️ Cambiar origen",
        )
    )
    rows = paginate(
        filas,
        pagina,
        more_id=f"lineas:{pagina + 1}",
        back_id=volver[0],
        more_title="➡️ Más líneas",
        back_title=volver[1],
    )
    return list_msg(
        body="¿Qué línea pasa por tu pueblo?",
        button_label="Ver líneas",
        sections=[section("Líneas", rows)],
        footer=_pie(cfg),
    )


def build_linea(cfg: BusConfig, linea: Linea, pueblos: list[tuple[str, str]], pagina: int) -> List:
    """pueblos: todos los (id, nombre) visibles de la línea; `pagina` ya es una
    página válida."""
    rows = paginate(
        [_fila_localidad(f"loc:{lid}", nombre) for lid, nombre in pueblos],
        pagina,
        more_id=f"linea:{linea.id}:{pagina + 1}",
        back_id="lineas:0",
        more_title="➡️ Ver más",
        back_title="↩️ Volver a líneas",
    )
    return list_msg(
        header=_cabecera(f"🚌 {linea.titulo}"),
        body="Elige tu pueblo:",
        button_label="Ver pueblos",
        sections=[section(linea.titulo, rows)],
        footer=_pie(cfg),
    )


# ── Día ────────────────────────────────────────────────────────────────


def build_dias(
    cfg: BusConfig,
    origen_nombre: str,
    destino_nombre: str,
    filas: list[tuple[str, str, str]],
    aviso: str | None = None,
) -> List:
    """filas: lista de (id "dia:<ISO>", titulo, descripcion), máximo 7."""
    rows = [row(id_, titulo, desc) for id_, titulo, desc in filas]
    rows.append(row("otra_fecha", "📅 Otra fecha"))
    return list_msg(
        header=_cabecera(f"🚌 {origen_nombre} → {destino_nombre}"),
        body=_con_aviso("¿Qué día viajas?", aviso),
        button_label="Ver días",
        sections=[section("Días", rows)],
        footer=_pie(cfg),
    )


# ── Resultado ─────────────────────────────────────────────────────────


def build_resultado(cfg: BusConfig, texto: str, botones: list[tuple[str, str]]) -> list[Reply]:
    """botones: lista de (id, titulo), máximo 3. El resultado va en el cuerpo de
    los botones si cabe (1.024); si no, como texto aparte (hasta 4.096), seguido
    de los botones (design.md §7.4)."""
    acciones = [button(id_, titulo) for id_, titulo in botones[:3]]
    if len(texto) <= MAX_INTERACTIVE_BODY:
        return [buttons_msg(body=texto, buttons=acciones, footer=_pie(cfg))]
    return [Text(texto), buttons_msg(body=msg.msg_que_mas(), buttons=acciones, footer=_pie(cfg))]
