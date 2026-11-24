"""Escenarios obligatorios del pack `bus`, con el arnés de
conversación en los dos tipos de canal. Cada respuesta pasa por los límites
comunes y por el renderizado de los dos adaptadores. Los datos son los
ficticios congelados (`fixtures/horarios_ficticios/`) salvo donde se indica.

La consulta completa de extremo a extremo (webhook → runtime → envío real) está en
`tests/integration/test_bus_pack.py`."""

from __future__ import annotations

import logging
from datetime import date

import pytest

from core.replies import Button, Buttons, List, Row, Text
from core.testing import Conversation
from core.testing.harness import ChannelType, Turn
from packs.bus import query
from packs.bus.datos import Datos
from packs.bus.matcher import Coincidencia
from packs.bus.pack import pack
from tests.packs.bus.demo import CONFIG, NEGOCIO_TELEFONO, datos_demo

MIERCOLES = "2026-09-23T10:00:00+02:00"  # laborable, dentro de la vigencia
MENU = ["🚌 Ver horarios", "ℹ️ Información"]
RESULTADO = ["📅 Otro día", "🔄 Ver la vuelta", "🔍 Otra consulta"]


@pytest.fixture(params=["whatsapp", "telegram"])
def canal(request: pytest.FixtureRequest) -> ChannelType:
    return request.param  # type: ignore[no-any-return]


def charla(canal: ChannelType, datos: Datos | None = None, now: str = MIERCOLES) -> Conversation:
    return Conversation(pack, config=CONFIG, data=datos or datos_demo(), channel=canal, now=now)


def hasta_dias(chat: Conversation) -> Turn:
    """Pozoluengo → Riomayor, hasta la lista de días."""
    chat.send("hola").expect(buttons=MENU)
    chat.press("menu_horarios").expect(list_includes="Pozoluengo")
    chat.press("loc:pozoluengo")
    return chat.press("loc:riomayor")


def cuerpo(turn: Turn) -> str:
    return "\n\n".join(r.body for r in turn.replies)


def filas(turn: Turn) -> list[Row]:
    """Las filas de la última lista de la respuesta."""
    lista = [r for r in turn.replies if isinstance(r, List)][-1]
    return [row for s in lista.sections for row in s.rows]


def botones(turn: Turn) -> list[Button]:
    """Los botones del último mensaje con botones de la respuesta."""
    return [r for r in turn.replies if isinstance(r, Buttons)][-1].buttons


def ids_de(turn: Turn) -> list[str]:
    """Ids de las filas de la última lista o, si no hay lista, de los botones."""
    if any(isinstance(r, List) for r in turn.replies):
        return [f.id for f in filas(turn)]
    return [b.id for b in botones(turn)]


def cero(fecha: str, offset: str = "+02:00") -> str:
    """Medianoche de `fecha` (ISO), para que ninguna salida de ese día haya salido ya."""
    return f"{fecha}T00:00:00{offset}"


# ── Camino feliz ──────────────────────────────────────────────────────────


def test_consulta_completa(canal: ChannelType) -> None:
    chat = charla(canal)
    dias = hasta_dias(chat)
    lista = dias.replies[-1]
    assert isinstance(lista, List) and lista.header == "🚌 Pozoluengo → Riomayor"
    ids = [r.id for s in lista.sections for r in s.rows]
    assert ids == [f"dia:2026-09-{d}" for d in range(23, 30)] + ["otra_fecha"]

    turn = chat.press("dia:2026-09-24").expect(buttons=RESULTADO)
    texto = cuerpo(turn)
    assert texto.startswith("🚌 Pozoluengo → Riomayor\n📅 Jueves 24/09")
    esperadas = query.consultar(datos_demo().horarios, "pozoluengo", "riomayor", date(2026, 9, 24))
    assert esperadas.estado == "con_salidas"
    for salida in esperadas.salidas:
        assert f"{salida.hora_salida:%H:%M} → {salida.hora_llegada:%H:%M}" in texto
    assert chat.state == {
        "step": "RESULTADO",
        "origen": "pozoluengo",
        "destino": "riomayor",
        "fecha": "2026-09-24",
    }


def test_ver_la_vuelta(canal: ChannelType) -> None:
    chat = charla(canal)
    hasta_dias(chat)
    chat.press("dia:2026-09-24")
    turn = chat.press("vuelta").expect(list_includes="📅 Otra fecha")
    lista = turn.replies[-1]
    assert isinstance(lista, List) and lista.header == "🚌 Riomayor → Pozoluengo"
    chat.press("dia:2026-09-24").expect(text_contains="🚌 Riomayor → Pozoluengo", buttons=RESULTADO)


def test_otro_dia(canal: ChannelType) -> None:
    chat = charla(canal)
    hasta_dias(chat)
    chat.press("dia:2026-09-24")
    chat.press("otro_dia").expect(list_includes="Mañana · jue 24/09")
    chat.press("dia:2026-09-25").expect(text_contains="📅 Viernes 25/09", buttons=RESULTADO)


def test_informacion(canal: ChannelType) -> None:
    chat = charla(canal)
    chat.send("hola")
    turn = chat.press("menu_info").expect(buttons=["🚌 Ver horarios", "↩️ Menú"])
    texto = cuerpo(turn)
    assert "📞 Teléfono: 600 00 00 00" in texto
    assert "lunes a miércoles laborables de 08:00 a 15:00 y de 17:00 a 19:00" in texto
    # `HttpUrl` normaliza una URL sin ruta con la barra final.
    assert texto.endswith("🌐 Web: https://www.autobuses-ejemplo.invalid/")


# ── Días sin salidas ──────────────────────────────────────────────────────


def test_dia_sin_servicio_ofrece_el_siguiente_dia(canal: ChannelType) -> None:
    chat = charla(canal)
    chat.send("hola")
    chat.press("menu_horarios")
    chat.send("Ribazo")  # no está en el menú de inicio: se escribe
    chat.press("loc:riomayor")
    turn = chat.press("dia:2026-09-26")  # sábado: sin servicio
    texto = cuerpo(turn)
    assert "Ese día no hay servicio" in texto
    assert "El siguiente día con salidas es lunes 28/09." in texto
    turn.expect(buttons=["📅 Día 28/9", "🔄 Ver la vuelta", "🔍 Otra consulta"])
    chat.press("dia:2026-09-28").expect(text_contains="📅 Lunes 28/09", buttons=RESULTADO)


def test_sin_datos_nunca_es_sin_servicio(canal: ChannelType) -> None:
    chat = charla(canal)
    hasta_dias(chat)
    chat.press("otra_fecha").expect(text_contains="día/mes")
    turn = chat.send("01/10/2027")  # fuera de la vigencia del calendario
    texto = cuerpo(turn)
    assert "No tengo el horario de ese día." in texto
    assert "no hay servicio" not in texto.lower()
    turn.expect(buttons=RESULTADO)


def test_25_de_diciembre_sin_servicio_en_ninguna_linea(canal: ChannelType) -> None:
    chat = charla(canal, now="2026-12-22T10:00:00+01:00")
    dias = hasta_dias(chat)
    lista = dias.replies[-1]
    assert isinstance(lista, List)
    fila = next(r for s in lista.sections for r in s.rows if r.id == "dia:2026-12-25")
    assert fila.description == "festivo · sin servicio"
    texto = cuerpo(chat.press("dia:2026-12-25"))
    assert "El 25/12 no hay servicio en ninguna línea." in texto
    assert "📞 600 00 00 00 (horario de oficina:" in texto


def test_hoy_sin_salidas_restantes_ofrece_manana(canal: ChannelType) -> None:
    chat = charla(canal, now="2026-09-23T23:30:00+02:00")
    dias = hasta_dias(chat)
    lista = dias.replies[-1]
    assert isinstance(lista, List)
    assert lista.sections[0].rows[0].description == "ya no quedan salidas hoy"
    turn = chat.press("dia:2026-09-23")
    assert "Hoy ya no quedan salidas." in cuerpo(turn)
    turn.expect(buttons=["📅 Mañana", "🔄 Ver la vuelta", "🔍 Otra consulta"])
    chat.press("dia:2026-09-24").expect(text_contains="📅 Jueves 24/09")


# ── Origen y destino ──────────────────────────────────────────────────────


def test_no_vendible(canal: ChannelType) -> None:
    chat = charla(canal)
    chat.send("hola")
    chat.press("menu_horarios")
    chat.press("loc:riomayor")
    turn = chat.send("Campoalto")
    assert "no vendemos billetes" in cuerpo(turn)
    assert chat.state["step"] == "SEL_DESTINO"


def test_sin_trayecto_directo(canal: ChannelType) -> None:
    chat = charla(canal)
    chat.send("hola")
    chat.press("menu_horarios")
    chat.press("loc:pozoluengo")
    turn = chat.send("Campoalto")
    assert "No hay trayecto directo de Pozoluengo a Campoalto." in cuerpo(turn)
    assert "📞 600 00 00 00" in cuerpo(turn)


def test_origen_igual_a_destino(canal: ChannelType) -> None:
    chat = charla(canal)
    chat.send("hola")
    chat.press("menu_horarios")
    chat.press("loc:pozoluengo")
    turn = chat.send("pozoluengo")
    assert "Elige un destino distinto." in cuerpo(turn)
    assert chat.state["step"] == "SEL_DESTINO"


@pytest.mark.parametrize("texto", ["villagrande", "villagrand"])
def test_villagrande_siempre_pregunta(canal: ChannelType, texto: str) -> None:
    chat = charla(canal)
    chat.send("hola")
    chat.press("menu_horarios")
    turn = chat.send(texto).expect(
        list_includes="Villagrande de Riomayor"
    )  # no cabe en un botón, va en lista
    lista = turn.replies[-1]
    assert isinstance(lista, List)
    ids = {r.id for s in lista.sections for r in s.rows}
    assert {"loc:villagrande-de-riomayor", "loc:villagrande-del-soto"} <= ids
    chat.press("loc:villagrande-de-riomayor").expect(text_contains="¿A dónde vas?")


def test_parada_homonima_en_dos_localidades_pregunta(canal: ChannelType) -> None:
    """ "Cruce Sur" es el nombre exacto de una parada en Corralejo y otra en Fontanar
    (X6): no debe resolver en silencio a una de las dos, debe preguntar cuál."""
    chat = charla(canal)
    chat.send("hola")
    chat.press("menu_horarios")
    turn = chat.send("Cruce Sur").expect(buttons=["Corralejo", "Fontanar"])
    botones = turn.replies[-1]
    assert isinstance(botones, Buttons)
    assert {b.id for b in botones.buttons} == {"loc:corralejo", "loc:fontanar"}


def test_errata_confirmada(canal: ChannelType) -> None:
    chat = charla(canal)
    chat.send("hola")
    chat.press("menu_horarios")
    chat.send("pozolengo").expect(text="¿Querías decir Pozoluengo?", buttons=["Sí", "No"])
    turn = chat.press("si")
    lista = turn.replies[-1]
    assert isinstance(lista, List) and lista.header == "🚌 Desde Pozoluengo"


def test_errata_rechazada(canal: ChannelType) -> None:
    chat = charla(canal)
    chat.send("hola")
    chat.press("menu_horarios")
    chat.send("pozolengo")
    chat.press("no").expect(text="Vale, escríbelo de otra forma.")
    assert chat.state["step"] == "ESCRIBIR_ORIGEN"
    chat.send("Pozoluengo").expect(text_contains="¿A dónde vas?")


def test_otro_nombre_ambiguo_en_vez_de_si_no_cambia_de_paso(canal: ChannelType) -> None:
    """X7: en vez de Sí/No se escribe otro nombre con varias coincidencias
    ("villagrande"): debe pasar a elegir de la lista, no quedarse atascado en
    CONFIRMAR_PUEBLO buscando cada botón pulsado como si fuera texto."""
    chat = charla(canal)
    chat.send("hola")
    chat.press("menu_horarios")
    chat.send("pozolengo")
    turn = chat.send("villagrande").expect(list_includes="Villagrande de Riomayor")
    lista = turn.replies[-1]
    assert isinstance(lista, List)
    ids = {r.id for s in lista.sections for r in s.rows}
    assert {"loc:villagrande-de-riomayor", "loc:villagrande-del-soto"} <= ids
    assert chat.state["step"] == "SEL_ORIGEN"
    chat.press("loc:villagrande-de-riomayor").expect(text_contains="¿A dónde vas?")


def test_otro_nombre_desconocido_en_vez_de_si_no_cambia_de_paso(canal: ChannelType) -> None:
    """X7: en vez de Sí/No se escribe un nombre sin ninguna coincidencia: debe
    volver a pedir el pueblo, no quedarse atascado respondiendo siempre lo mismo."""
    chat = charla(canal)
    chat.send("hola")
    chat.press("menu_horarios")
    chat.send("pozolengo")
    chat.send("zzzz")
    assert chat.state["step"] == "SEL_ORIGEN"
    chat.send("Pozoluengo").expect(text_contains="¿A dónde vas?")


def test_pueblo_desconocido_ofrece_pueblos_por_linea(
    canal: ChannelType, caplog: pytest.LogCaptureFixture
) -> None:
    chat = charla(canal)
    chat.send("hola")
    chat.press("menu_horarios")
    caplog.set_level(logging.INFO, logger="packs.bus")
    turn = chat.send("Ciudad Inventada 612345678")
    assert "No conozco ese pueblo." in cuerpo(turn)
    turn.expect(list_includes="🚌 Ver pueblos por línea")
    (registro,) = [r for r in caplog.records if "[NO_RECONOCIDO]" in r.getMessage()]
    # Ni el identificador del contacto ni su teléfono, ni el número escrito.
    assert registro.getMessage() == "[NO_RECONOCIDO] paso=origen longitud=26"
    assert "612345678" not in registro.getMessage()
    assert chat.contact.external_id not in registro.getMessage()


def test_pueblos_por_linea_con_paginacion(canal: ChannelType, datos_muchas_lineas: Datos) -> None:
    chat = charla(canal, datos_muchas_lineas)
    chat.send("hola")
    chat.press("menu_horarios")
    chat.send("zzzz")
    turn = chat.press("lineas:0")
    lista = turn.replies[-1]
    assert isinstance(lista, List)
    filas = [r for s in lista.sections for r in s.rows]
    assert len(filas) == 10
    assert [f.id for f in filas[-2:]] == ["lineas:1", "menu"]
    turn = chat.press("lineas:1").expect(list_includes="Ruta del norte")
    chat.press("linea:linea-larga:0").expect(list_includes="➡️ Ver más")
    chat.press("linea:linea-larga:1").expect(list_includes="➡️ Ver más")
    turn = chat.press("linea:linea-larga:2").expect(list_includes="↩️ Volver a líneas")
    lista = turn.replies[-1]
    assert isinstance(lista, List)
    assert [r.id for s in lista.sections for r in s.rows][-1] == "lineas:0"
    # Una página que no existe vuelve a la lista de líneas.
    chat.press("linea:linea-larga:9", check=False).expect(list_includes="➡️ Más líneas")
    chat.press("loc:origen")  # Origen, en la lista de pueblos de la línea
    assert chat.state["origen"] == "origen"


def test_localidad_pendiente(canal: ChannelType, datos_pendientes: Datos) -> None:
    chat = charla(canal, datos_pendientes)
    chat.send("hola")
    chat.press("menu_horarios")
    turn = chat.send("Aldea A")
    assert "aún no tenemos su hora de paso" in cuerpo(turn)
    turn.expect(buttons=["Usar Pueblo A", "✍️ Otro pueblo"])
    chat.press("usar:pueblo-a").expect(text_contains="¿A dónde vas?")
    assert chat.state["origen"] == "pueblo-a"


# ── Fechas escritas ───────────────────────────────────────────────────────


def test_fecha_pasada(canal: ChannelType) -> None:
    chat = charla(canal)
    hasta_dias(chat)
    chat.press("otra_fecha")
    chat.send("20/09").expect(
        text="Esa fecha ya ha pasado. 📅 Escribe la fecha así: día/mes\nPor ejemplo: 25/12"
    )
    assert chat.state["step"] == "ESCRIBIR_FECHA"


@pytest.mark.parametrize("texto", ["32/13", "mañana", "el viernes"])
def test_fecha_escrita_invalida(canal: ChannelType, texto: str) -> None:
    chat = charla(canal)
    hasta_dias(chat)
    chat.press("otra_fecha")
    chat.send(texto).expect(
        text="No he entendido la fecha. Escríbela así: día/mes, por ejemplo 25/12."
    )
    chat.send("1/10").expect(text_contains="📅 Jueves 01/10", buttons=RESULTADO)


# ── Resultado de más de 4.096 caracteres ──────────────────────────────────


def test_resultado_largo_se_corta_y_va_aparte(
    canal: ChannelType, datos_muchas_salidas: Datos
) -> None:
    chat = charla(canal, datos_muchas_salidas, now="2026-09-23T00:00:00+02:00")
    chat.send("hola")
    chat.press("menu_horarios")
    chat.press("loc:origen")
    turn = chat.press("loc:destino")
    turn = chat.press("dia:2026-09-24")
    texto, botones = turn.replies
    assert isinstance(texto, Text) and isinstance(botones, Buttons)
    assert len(texto.body) <= 4096
    assert texto.body.startswith("🚌 Origen → Destino")
    assert "salidas más. Para verlas todas, llama al 600 00 00 00." in texto.body
    assert "05:00 → 05:55" in texto.body
    turn.expect(text="¿Qué quieres hacer ahora?", buttons=RESULTADO)


# ── Comandos comunes y entradas raras ─────────────────────────────────────


def test_menu_global_reinicia_la_consulta(canal: ChannelType) -> None:
    chat = charla(canal)
    hasta_dias(chat)
    chat.send("menú").expect(buttons=MENU)
    assert chat.state == {}
    chat.send("salir")
    assert chat.state == {}


def test_audio_o_imagen(canal: ChannelType) -> None:
    chat = charla(canal)
    hasta_dias(chat)
    chat.unsupported().expect(
        text="No puedo leer audios, imágenes ni stickers. Escríbeme o usa los botones."
    )
    assert chat.state["step"] == "SEL_DIA"  # no pierde la consulta


def test_estado_manipulado_vuelve_al_menu(canal: ChannelType) -> None:
    chat = charla(canal)
    hasta_dias(chat)
    chat.state["origen"] = "pueblo-que-ya-no-existe"
    chat.press("otro_dia", check=False).expect(buttons=MENU)
    assert chat.state == {}


# ── Fecha escrita: siempre hay salida y nunca se adivina el año ───────────────

SALIDA_FECHA = ["📅 Ver lista de días", "↩️ Menú"]


def test_fecha_no_entendida_ofrece_salida(canal: ChannelType) -> None:
    chat = charla(canal)
    hasta_dias(chat)
    chat.press("otra_fecha").expect(buttons=SALIDA_FECHA)
    chat.send("mañana").expect(text_contains="No he entendido la fecha", buttons=SALIDA_FECHA)
    chat.send("10 30").expect(text_contains="No he entendido la fecha", buttons=SALIDA_FECHA)
    chat.send("20/09").expect(text_contains="ya ha pasado", buttons=SALIDA_FECHA)
    assert chat.state["step"] == "ESCRIBIR_FECHA"
    chat.press("ver_dias").expect(list_includes="Hoy")
    assert chat.state["step"] == "SEL_DIA"
    chat.press("otra_fecha")
    chat.press("menu").expect(buttons=MENU)
    assert chat.state == {}


@pytest.mark.parametrize("palabra", ["cancelar", "Volver", "atrás", "Salir."])
def test_palabras_de_escape_vuelven_al_menu_en_la_fecha(canal: ChannelType, palabra: str) -> None:
    chat = charla(canal)
    hasta_dias(chat)
    chat.press("otra_fecha")
    chat.send(palabra).expect(buttons=MENU)
    assert chat.state == {}


def test_fecha_sin_anio_en_otro_anio_se_pregunta(canal: ChannelType) -> None:
    chat = charla(canal)
    hasta_dias(chat)
    chat.press("otra_fecha")
    # 23/08 ya pasó hace un mes: no se salta en silencio a 2027.
    chat.send("23/08").expect(text="¿Te refieres al 23/08/2027?", buttons=["Sí", "No"])
    assert chat.state["step"] == "CONFIRMAR_FECHA"
    chat.press("no").expect(text_contains="Escribe la fecha", buttons=SALIDA_FECHA)
    chat.send("23/08")
    turn = chat.press("si")
    assert "/2027" in cuerpo(turn)  # el año se muestra en el resultado
    assert chat.state["step"] == "RESULTADO" and chat.state["fecha"] == "2027-08-23"


def test_29_de_febrero_no_salta_en_silencio(canal: ChannelType) -> None:
    chat = charla(canal)
    hasta_dias(chat)
    chat.press("otra_fecha")
    chat.send("29/02").expect(text="¿Te refieres al 29/02/2028?", buttons=["Sí", "No"])
    chat.send("sí").expect(text_contains="29/02/2028")


def test_fecha_en_la_lista_de_dias_tambien_pregunta(canal: ChannelType) -> None:
    chat = charla(canal)
    hasta_dias(chat)
    chat.send("23/08").expect(text="¿Te refieres al 23/08/2027?")
    chat.send("hola").expect(buttons=MENU)


# ── Botones viejos y de otros pasos ────────────────────────────────────────────


def test_loc_viejo_en_confirmar_pueblo_se_elige(canal: ChannelType) -> None:
    chat = charla(canal)
    chat.send("hola")
    chat.press("menu_horarios")
    chat.send("pozolengo").expect(buttons=["Sí", "No"])
    assert chat.state["step"] == "CONFIRMAR_PUEBLO"
    chat.press("loc:riomayor", check=False).expect(list_includes="Pozoluengo")
    assert chat.state["origen"] == "riomayor" and chat.state["step"] == "SEL_DESTINO"


def test_loc_desconocido_en_confirmar_pueblo_repite_el_paso(canal: ChannelType) -> None:
    chat = charla(canal)
    chat.send("hola")
    chat.press("menu_horarios")
    chat.send("pozolengo")
    chat.press("loc:no-existe", check=False).expect(list_includes="Riomayor")
    assert "origen" not in chat.state


def test_boton_de_otro_paso_en_confirmar_pueblo_repite_la_pregunta(canal: ChannelType) -> None:
    chat = charla(canal)
    chat.send("hola")
    chat.press("menu_horarios")
    chat.send("pozolengo")
    chat.press("otro_dia", check=False).expect(text_contains="Pozoluengo", buttons=["Sí", "No"])
    assert chat.state["step"] == "CONFIRMAR_PUEBLO"


def test_boton_de_otro_paso_en_sel_origen_no_es_un_pueblo(
    canal: ChannelType, caplog: pytest.LogCaptureFixture
) -> None:
    chat = charla(canal)
    chat.send("hola")
    chat.press("menu_horarios")
    caplog.set_level(logging.INFO, logger="packs.bus")
    turn = chat.press("dia:2026-09-24", check=False).expect(list_includes="Pozoluengo")
    assert "No conozco" not in cuerpo(turn)
    assert not [r for r in caplog.records if "[NO_RECONOCIDO]" in r.getMessage()]
    assert chat.state["step"] == "SEL_ORIGEN"


def test_dia_ya_pasado_repite_la_lista_de_dias(canal: ChannelType) -> None:
    chat = charla(canal)
    hasta_dias(chat)
    chat.press("dia:2026-09-22", check=False).expect(
        text_contains="Esa fecha ya ha pasado", list_includes="Hoy"
    )
    assert chat.state["step"] == "SEL_DIA"
    chat.press("dia:2026-09-24")
    chat.press("dia:2026-09-01", check=False).expect(text_contains="ya ha pasado")
    assert chat.state["step"] == "SEL_DIA"


# ── Logs sin texto libre ───────────────────────────────────────────────────────


def test_los_logs_no_llevan_lo_que_escribe_el_cliente(
    canal: ChannelType, caplog: pytest.LogCaptureFixture
) -> None:
    chat = charla(canal)
    hasta_dias(chat)
    caplog.set_level(logging.INFO, logger="packs.bus")
    chat.send("Juan Pérez 666")
    chat.press("otra_fecha")
    chat.send("quedamos el viernes")
    registros = [r.getMessage() for r in caplog.records if "[NO_RECONOCIDO]" in r.getMessage()]
    assert registros and all("longitud=" in r for r in registros)
    assert not any(t in " ".join(registros) for t in ("Juan", "viernes", "666"))


# ── Resultado larguísimo: recorte con aviso y notas coherentes ──────────────────


def test_resultado_recortado_solo_explica_las_notas_visibles(canal: ChannelType) -> None:
    from datetime import time

    from packs.bus.calendario import InfoDia
    from packs.bus.messages import msg_resultado
    from packs.bus.query import Consulta, Salida

    salidas = tuple(
        Salida(
            hora_salida=time(6, 0),
            hora_llegada=time(8, 0),
            duracion_min=120,
            parada_origen="POZ",
            parada_destino="RIO",
            lineas=("pozoluengo-riomayor",),
            notas=(f"Nota {i} " + "x" * 60,),
        )
        for i in range(120)
    )
    info = InfoDia(date(2026, 9, 23), "miercoles", "miercoles", False, None, True, 9)
    consulta = Consulta("con_salidas", salidas, info, (), (), False, None)
    texto = msg_resultado(CONFIG, consulta, datos_demo().horarios, "A", "B", date(2026, 9, 23))
    assert len(texto) <= 4096 and "salidas más" in texto
    assert "Nota 119" not in texto


# ── Entradas fuera de lugar y caducidad ───────────────────────────────────────


def test_estado_caducado_vuelve_al_menu(canal: ChannelType) -> None:
    chat = charla(canal)
    chat.send("hola")
    chat.press("menu_horarios")
    chat.press("loc:pozoluengo")
    # La caducidad (30 min) la aplica la plataforma: pasada, el siguiente mensaje
    # empieza en el menú.
    chat.now("2026-09-23T10:31:00+02:00")
    turn = chat.press("loc:riomayor", check=False)
    assert "necesitas" in cuerpo(turn).lower()
    assert chat.state == {}


def test_id_desconocido_en_el_menu_vuelve_al_menu(canal: ChannelType) -> None:
    """Un id de otro paso nunca se trata como válido en el menú."""
    chat = charla(canal)
    turn = chat.press("dia:2020-01-01", check=False)
    assert "necesitas" in cuerpo(turn).lower()
    turn.expect(buttons=MENU)


def test_status_no_es_un_comando_del_pack(canal: ChannelType) -> None:
    """`/status` y similares son de la plataforma; para el pack son texto normal."""
    chat = charla(canal)
    turn = chat.send("/status")
    assert len(turn.replies) == 1
    assert "necesitas" in cuerpo(turn).lower()


def test_un_solo_mensaje_por_entrada(canal: ChannelType) -> None:
    chat = charla(canal)
    chat.send("hola")
    chat.press("menu_horarios")
    assert len(chat.press("loc:pozoluengo").replies) == 1


# ── Casos del motor: líneas sin datos, a demanda, viernes lectivo… ──────────────
# Datos sintéticos de `fixtures/horarios_motor/`.


def trayecto(chat: Conversation, origen: str, destino: str) -> Turn:
    """Escribe los dos pueblos y devuelve la lista de días."""
    chat.send("hola")
    chat.press("menu_horarios")
    chat.send(origen)
    return chat.send(destino)


def test_sin_servicio_a_mas_de_7_dias_ofrece_boton_del_dia(
    canal: ChannelType, datos_motor: Datos
) -> None:
    chat = charla(canal, datos_motor, cero("2026-09-23"))  # dentro del no_circula [septiembre]
    trayecto(chat, "pueblo p", "pueblo q")
    turn = chat.press("dia:2026-09-23")
    assert len(turn.replies) == 1
    assert "Ese día no hay servicio en este trayecto." in cuerpo(turn)
    assert "jueves 01/10" in cuerpo(turn)
    assert "dia:2026-10-01" in ids_de(turn)
    assert all(len(b.title) <= 20 for b in botones(turn))


def test_sin_servicio_sin_dia_con_salidas_en_45_dias_da_telefono(
    canal: ChannelType, datos_motor: Datos
) -> None:
    chat = charla(canal, datos_motor, cero("2026-08-01"))
    trayecto(chat, "pueblo p", "pueblo q")
    turn = chat.press("dia:2026-08-01")
    texto = cuerpo(turn)
    assert "no hay salidas" in texto.lower()
    assert "📞" in texto or "600" in texto
    assert not any(i.startswith("dia:") for i in ids_de(turn))


def test_dia_sin_datos_no_es_sin_servicio(canal: ChannelType, datos_motor: Datos) -> None:
    chat = charla(canal, datos_motor, cero("2026-09-23"))
    dias = trayecto(chat, "pueblo g", "pueblo h")
    assert len(dias.replies) == 1
    hoy = next(f for f in filas(dias) if f.id == "dia:2026-09-23")
    assert hoy.description == "horario no disponible"
    turn = chat.press("dia:2026-09-23")
    assert len(turn.replies) == 1
    texto = cuerpo(turn).lower()
    assert "no hay servicio" not in texto
    assert "no tengo el horario" in texto


def test_fecha_fuera_de_vigencia_da_sin_datos(canal: ChannelType, datos_motor: Datos) -> None:
    chat = charla(canal, datos_motor, cero("2026-09-23"))
    trayecto(chat, "pueblo a", "pueblo b")
    chat.press("otra_fecha")
    turn = chat.send("01/10/2027")
    assert len(turn.replies) == 1
    texto = cuerpo(turn).lower()
    assert "no tengo el horario" in texto
    assert "no hay servicio" not in texto


def test_salidas_con_linea_sin_datos_avisa(canal: ChannelType, datos_motor: Datos) -> None:
    chat = charla(canal, datos_motor, cero("2026-09-23"))
    dias = trayecto(chat, "pueblo e", "pueblo f")
    hoy = next(f for f in filas(dias) if f.id == "dia:2026-09-23")
    assert "puede haber más" in (hoy.description or "")
    turn = chat.press("dia:2026-09-23")
    assert len(turn.replies) == 1
    assert "puede haber más" in cuerpo(turn).lower()


def test_a_demanda_incluye_el_telefono_de_la_linea(canal: ChannelType, datos_motor: Datos) -> None:
    chat = charla(canal, datos_motor, cero("2026-09-23"))
    trayecto(chat, "pueblo k", "pueblo l")
    turn = chat.press("dia:2026-09-23")
    assert len(turn.replies) == 1
    assert "600 55 55 55" in cuerpo(turn)


def test_viernes_lectivo_solo_corre_en_viernes_de_curso(
    canal: ChannelType, datos_motor: Datos
) -> None:
    chat = charla(canal, datos_motor, cero("2026-09-23"))
    trayecto(chat, "pueblo a", "pueblo b")
    assert "09:00" not in cuerpo(chat.press("dia:2026-09-24"))  # jueves
    texto = cuerpo(chat.press("dia:2026-09-25"))  # viernes lectivo
    assert "09:00" in texto
    assert "Solo viernes en periodo escolar." in texto


def test_horas_aproximadas_sin_marca_numerica(canal: ChannelType, datos_motor: Datos) -> None:
    chat = charla(canal, datos_motor, cero("2026-09-23"))
    trayecto(chat, "pueblo r", "pueblo s")
    turn = chat.press("dia:2026-09-23")
    assert len(turn.replies) == 1
    texto = cuerpo(turn)
    assert "⚠️ Horarios de paso aproximados." in texto
    assert not any(marca in texto for marca in "¹²³⁴⁵⁶⁷⁸⁹")


def test_ver_la_vuelta_sin_trayecto_llega_en_un_solo_mensaje(
    canal: ChannelType, datos_motor: Datos
) -> None:
    """Sin trayecto de vuelta, `plan_sends` mete el texto en el cuerpo del menú."""
    chat = charla(canal, datos_motor, cero("2026-09-23"))
    trayecto(chat, "pueblo a", "pueblo c")
    chat.press("dia:2026-09-23")
    turn = chat.press("vuelta")
    assert len(turn.replies) == 1
    texto = cuerpo(turn).lower()
    assert "trayecto" in texto and "necesitas" in texto


def test_otra_consulta_muestra_la_lista_de_origen(canal: ChannelType) -> None:
    chat = charla(canal, now=cero("2026-09-23"))
    hasta_dias(chat)
    chat.press("dia:2026-09-23")
    turn = chat.press("otra_consulta")
    assert len(turn.replies) == 1
    assert "pueblo" in cuerpo(turn).lower()


# ── Pueblos por línea ─────────────────────────────────────────────────────


def hasta_escribir(chat: Conversation) -> Turn:
    """Menú → horarios → «Otro pueblo», con los botones de escribir."""
    chat.send("hola")
    chat.press("menu_horarios")
    return chat.press("escribir")


def test_lineas_en_origen_caben_en_una_pagina(canal: ChannelType) -> None:
    chat = charla(canal)
    hasta_escribir(chat)
    turn = chat.press("lineas:0")
    assert len(turn.replies) == 1
    assert cuerpo(turn) == "¿Qué línea pasa por tu pueblo?"
    lista = ids_de(turn)
    # Las 8 líneas ficticias caben en una sola página: 8 + volver = 9 filas.
    assert len(lista) == 9
    assert not any(i.startswith("lineas:") for i in lista)
    assert lista[0] == "linea:pozoluengo-riomayor:0" and lista[-1] == "menu"
    assert filas(turn)[0].title == "Pozoluengo – Riomayor"
    assert filas(turn)[0].description == "3 pueblos"


def test_origen_por_linea_y_pueblo_lleva_a_los_destinos(canal: ChannelType) -> None:
    chat = charla(canal)
    hasta_escribir(chat)
    chat.press("lineas:0")
    turn = chat.press("linea:riomayor-pinarnuevo:0")
    lista = ids_de(turn)
    lista_lineas = [r for r in turn.replies if isinstance(r, List)][-1]
    assert lista_lineas.header == "🚌 Riomayor – Pinarnuevo"
    pueblos = [i for i in lista if i.startswith("loc:")]
    assert len(pueblos) == 4 and pueblos == sorted(pueblos)  # en orden alfabético
    assert lista[-1] == "lineas:0" and "loc:valdejunco" in lista

    chat.press("lineas:0")
    assert "loc:pozoluengo" in ids_de(chat.press("linea:pozoluengo-riomayor:0"))
    turn = chat.press("loc:pozoluengo")
    assert "Desde Pozoluengo" in [r for r in turn.replies if isinstance(r, List)][-1].header  # type: ignore[operator]
    assert chat.state["origen"] == "pozoluengo"


def test_fuenteclara_esta_en_su_propia_linea(canal: ChannelType) -> None:
    chat = charla(canal)
    hasta_escribir(chat)
    assert "loc:fuenteclara" in ids_de(chat.press("linea:riomayor-fuenteclara:0", check=False))


def test_lineas_en_destino_solo_las_alcanzables_desde_el_origen(canal: ChannelType) -> None:
    chat = charla(canal)
    chat.send("hola")
    chat.press("menu_horarios")
    chat.press("loc:pozoluengo")
    chat.press("escribir")
    turn = chat.press("lineas:0")
    assert len(turn.replies) == 1
    lista = ids_de(turn)
    # Pozoluengo solo tiene una línea: las demás quedan fuera de la lista.
    assert {i.split(":")[1] for i in lista if i.startswith("linea:")} == {"pozoluengo-riomayor"}
    assert lista[-1] == "cambiar_origen"
    # "N pueblos" cuenta los alcanzables desde el origen en esa línea.
    assert {f.id: f.description for f in filas(turn)}["linea:pozoluengo-riomayor:0"] == "2 pueblos"

    pueblos = {i for i in ids_de(chat.press("linea:pozoluengo-riomayor:0")) if i.startswith("loc:")}
    assert pueblos == {"loc:carrascal", "loc:riomayor"}  # sin el propio origen
    assert any(i.startswith("dia:") for i in ids_de(chat.press("loc:riomayor")))


def test_lineas_en_destino_volver_es_cambiar_origen(canal: ChannelType) -> None:
    chat = charla(canal)
    chat.send("hola")
    chat.press("menu_horarios")
    chat.press("loc:pozoluengo")
    chat.press("escribir")
    chat.press("lineas:0")
    turn = chat.press("cambiar_origen")
    assert "pueblo" in cuerpo(turn).lower()
    assert "loc:pozoluengo" in ids_de(turn)
    assert chat.state["step"] == "SEL_ORIGEN" and "origen" not in chat.state


def test_lineas_en_destino_volver_a_lineas_desde_una_linea(canal: ChannelType) -> None:
    chat = charla(canal)
    chat.send("hola")
    chat.press("menu_horarios")
    chat.press("loc:pozoluengo")
    chat.press("lineas:0", check=False)
    assert ids_de(chat.press("linea:pozoluengo-riomayor:0"))[-1] == "lineas:0"
    assert ids_de(chat.press("lineas:0"))[-1] == "cambiar_origen"


@pytest.mark.parametrize(
    "valor",
    [
        "linea:no-existe:0",
        "linea:pozoluengo-riomayor:99",
        "linea:pozoluengo-riomayor:-1",
        "linea:x",
        "linea:x:abc",
        "linea:x:-1",
        "linea:pozoluengo-riomayor:abc",
        "linea:a:b:c",
        "linea:",
        "lineas:zz",
        "lineas:99",
        "lineas:-3",
        "lineas:",
    ],
)
def test_ids_malformados_muestran_la_lista_de_lineas(canal: ChannelType, valor: str) -> None:
    chat = charla(canal)
    hasta_escribir(chat)
    turn = chat.press(valor, check=False)
    assert len(turn.replies) == 1
    assert cuerpo(turn) == "¿Qué línea pasa por tu pueblo?"
    assert ids_de(turn)[0] == "linea:pozoluengo-riomayor:0"


@pytest.mark.parametrize(
    "valor",
    [
        "linea:riomayor-ribazo:0",  # existe, pero no sale de Pozoluengo
        "linea:no-existe:0",
        "linea:x:abc",
        "linea:pozoluengo-riomayor:-1",
        "linea:pozoluengo-riomayor:99",
        "lineas:zz",
    ],
)
def test_ids_malformados_en_destino_muestran_la_lista_de_lineas(
    canal: ChannelType, valor: str
) -> None:
    chat = charla(canal)
    chat.send("hola")
    chat.press("menu_horarios")
    chat.press("loc:pozoluengo")
    turn = chat.press(valor, check=False)
    assert cuerpo(turn) == "¿Qué línea pasa por tu pueblo?"
    lista = ids_de(turn)
    assert "linea:pozoluengo-riomayor:0" in lista  # es la única línea de Pozoluengo
    assert lista[-1] == "cambiar_origen"


def test_pueblo_desconocido_ofrece_las_lineas_y_estas_llevan_a_la_lista(
    canal: ChannelType,
) -> None:
    chat = charla(canal)
    chat.send("hola")
    chat.press("menu_horarios")
    turn = chat.send("xyzxyz")
    assert "No conozco ese pueblo" in cuerpo(turn)
    assert Row("lineas:0", "🚌 Ver pueblos por línea") in filas(turn)
    assert ids_de(chat.press("lineas:0"))[0] == "linea:pozoluengo-riomayor:0"


def test_pueblo_desconocido_en_destino_ofrece_las_lineas(
    canal: ChannelType, datos_muchas_lineas: Datos
) -> None:
    chat = charla(canal, datos_muchas_lineas)
    chat.send("hola")
    chat.press("menu_horarios")
    chat.press("loc:origen")
    turn = chat.send("xyzxyz")
    assert "No conozco ese pueblo" in cuerpo(turn)
    assert "lineas:0" in ids_de(turn)


def test_escribir_ofrece_el_boton_de_ver_por_linea(canal: ChannelType) -> None:
    chat = charla(canal)
    chat.send("hola")
    chat.press("menu_horarios")
    assert botones(chat.press("escribir"))[0] == Button("lineas:0", "🚌 Ver por línea")
    chat.press("loc:pozoluengo")
    segundo = botones(chat.press("escribir"))
    assert [b.id for b in segundo[:2]] == ["lineas:0", "cambiar_origen"]


def test_errata_rechazada_ofrece_tambien_ver_por_linea(canal: ChannelType) -> None:
    chat = charla(canal)
    chat.send("hola")
    chat.press("menu_horarios")
    chat.send("pozolengo")
    turn = chat.press("no")
    assert "otra forma" in cuerpo(turn).lower()
    assert "lineas:0" in ids_de(turn)
    assert chat.state["step"] == "ESCRIBIR_ORIGEN"


def test_muchas_lineas_titulo_corto_y_paginas_de_pueblos(
    canal: ChannelType, datos_muchas_lineas: Datos
) -> None:
    chat = charla(canal, datos_muchas_lineas)
    hasta_escribir(chat)
    lista = ids_de(chat.press("lineas:0"))
    assert len(lista) == 10 and lista[8] == "lineas:1"
    turn = chat.press("lineas:1")
    assert ids_de(turn)[-2:] == ["linea:ruta-norte:0", "menu"]
    ruta = filas(turn)[-2]
    assert ruta.title == "Ruta del norte"
    assert ruta.description == "Ruta muy larga del norte al sur de la sierra · 3 pueblos"
    # La línea de 19 pueblos ocupa 3 páginas; la última ya no tiene «ver más».
    assert "linea:linea-larga:1" in ids_de(chat.press("linea:linea-larga:0"))
    assert "linea:linea-larga:2" in ids_de(chat.press("linea:linea-larga:1"))
    ultima = ids_de(chat.press("linea:linea-larga:2"))
    assert len([i for i in ultima if i.startswith("loc:")]) == 3
    assert not any(i.startswith("linea:") for i in ultima)


def test_destino_con_muchas_lineas_solo_las_del_origen(
    canal: ChannelType, datos_muchas_lineas: Datos
) -> None:
    chat = charla(canal, datos_muchas_lineas)
    chat.send("hola")
    chat.press("menu_horarios")
    assert "escribir" in ids_de(chat.press("loc:origen"))  # 30 destinos: no caben en la lista
    chat.press("escribir")
    lista = ids_de(chat.press("lineas:0"))
    assert len(lista) == 10 and lista[8] == "lineas:1"
    assert "loc:origen" not in ids_de(chat.press("linea:linea-larga:0", check=False))


def test_origen_con_mas_de_9_destinos_muestra_10_filas(
    canal: ChannelType, datos_muchas_lineas: Datos
) -> None:
    chat = charla(canal, datos_muchas_lineas)
    chat.send("hola")
    chat.press("menu_horarios")
    turn = chat.press("loc:origen")
    assert len(turn.replies) == 1
    assert len(filas(turn)) == 10
    assert any("Otro destino" in f.title for f in filas(turn))


def test_aldea_pendiente_no_sale_en_ninguna_linea(
    canal: ChannelType, datos_pendientes: Datos
) -> None:
    chat = charla(canal, datos_pendientes)
    hasta_escribir(chat)
    lineas = [i for i in ids_de(chat.press("lineas:0")) if i.startswith("linea:")]
    assert lineas
    for fila in lineas:
        pueblos = ids_de(chat.press(fila, check=False))
        assert "loc:aldea-a" not in pueblos and "loc:aldea-b" not in pueblos


def test_demasiadas_coincidencias_pide_algo_mas_concreto(
    canal: ChannelType, monkeypatch: pytest.MonkeyPatch
) -> None:
    chat = charla(canal)
    chat.send("hola")
    chat.press("menu_horarios")
    monkeypatch.setattr(
        datos_demo().matcher,
        "buscar",
        lambda texto: Coincidencia(tipo="demasiadas", localidades=(), texto_normalizado="a"),
    )
    turn = chat.send("a")
    assert len(turn.replies) == 1
    assert "concreto" in cuerpo(turn).lower()


# ── Fecha escrita en la lista de días ───────────────────────────────────────────


def test_fecha_escrita_directamente_en_la_lista_de_dias(canal: ChannelType) -> None:
    chat = charla(canal)
    hasta_dias(chat)
    turn = chat.send("25/12")
    assert len(turn.replies) == 1
    assert botones(turn)  # un resultado, con sus botones


def test_texto_no_valido_en_la_lista_de_dias_vuelve_a_la_lista(canal: ChannelType) -> None:
    chat = charla(canal)
    hasta_dias(chat)
    turn = chat.send("mañana")
    assert len(turn.replies) == 1
    assert filas(turn) and "lista" in cuerpo(turn).lower()


def test_fecha_pasada_en_la_lista_de_dias_es_un_solo_mensaje(canal: ChannelType) -> None:
    chat = charla(canal)
    hasta_dias(chat)
    turn = chat.send("20/09")
    assert len(turn.replies) == 1
    assert "pasado" in cuerpo(turn).lower()


# ── Logs sin el número escrito ──────────────────────────────────────────────────


@pytest.mark.parametrize("numero", ["612345678", "612 34 56 78"])
def test_numero_escrito_como_fecha_no_llega_a_los_logs(
    canal: ChannelType, caplog: pytest.LogCaptureFixture, numero: str
) -> None:
    """`formato.normalizar()` sustituye separadores por espacios: un número escrito con
    espacios o guiones no debe colar como si tuviera menos de 6 dígitos seguidos."""
    chat = charla(canal)
    hasta_dias(chat)
    chat.press("otra_fecha")
    caplog.set_level(logging.INFO, logger="packs.bus")
    assert len(chat.send(numero).replies) == 1
    assert not any(numero in r.getMessage() for r in caplog.records)
    (registro,) = [r.getMessage() for r in caplog.records if "[NO_RECONOCIDO]" in r.getMessage()]
    assert registro == f"[NO_RECONOCIDO] paso=fecha longitud={len(numero)}"


# ── Sin servicio en ninguna línea y festivos locales ────────────────────────────


def test_25_de_diciembre_explica_el_festivo_y_ofrece_el_siguiente_dia(canal: ChannelType) -> None:
    chat = charla(canal, now="2026-12-22T10:00:00+01:00")
    dias = hasta_dias(chat)
    assert len(next(f for f in filas(dias) if f.id == "dia:2026-12-25").description or "") <= 72
    turn = chat.press("dia:2026-12-25")
    texto = cuerpo(turn)
    assert "festivo (Navidad)" in texto
    assert NEGOCIO_TELEFONO in texto
    assert "sábado 26/12" in texto
    assert "dia:2026-12-26" in ids_de(turn)
    assert "No hay salidas en los próximos días" not in texto


def test_festivo_local_de_odalla_en_la_lista_y_en_el_resultado(canal: ChannelType) -> None:
    chat = charla(canal, now="2026-10-10T10:00:00+02:00")
    chat.send("hola")
    chat.press("menu_horarios")
    chat.press("loc:riomayor")
    dias = chat.press("loc:odalla")
    por_id = {f.id: f for f in filas(dias)}
    descripcion = por_id["dia:2026-10-14"].description or ""
    assert descripcion.startswith("festivo · ") and len(descripcion) <= 72
    assert not (por_id["dia:2026-10-13"].description or "").startswith("festivo")
    texto = cuerpo(chat.press("dia:2026-10-14"))
    assert "festivo en Odalla (Fiesta local de Odalla)" in texto
    assert "09:00" in texto


# ── Trayectos no vendibles y sin trayecto, escritos ─────────────────────────────


def test_destino_no_vendible_no_se_ofrece_y_no_es_sin_trayecto(canal: ChannelType) -> None:
    chat = charla(canal)
    chat.send("hola")
    chat.press("menu_horarios")
    chat.press("loc:riomayor")
    turn = chat.send("Campoalto")
    texto = cuerpo(turn)
    assert "no vendemos billetes" in texto
    assert "Riomayor" in texto and "Campoalto" in texto
    assert "No hay trayecto directo" not in texto
    assert "loc:campoalto" not in ids_de(turn)


def test_destino_sin_trayecto_no_es_no_vendible(canal: ChannelType) -> None:
    chat = charla(canal)
    chat.send("hola")
    chat.press("menu_horarios")
    chat.press("loc:pozoluengo")
    texto = cuerpo(chat.send("campoalto"))
    assert "No hay trayecto directo" in texto and "no vendemos" not in texto


def test_ver_la_vuelta_de_un_par_no_vendible_da_su_propio_mensaje(canal: ChannelType) -> None:
    """Rama defensiva de «ver la vuelta»: se fuerza un estado cuyo par invertido
    (campoalto → pinarnuevo) es no vendible. El aviso llega en el cuerpo del menú."""
    chat = charla(canal, now=cero("2026-09-23"))
    chat.send("hola")
    chat.press("menu_horarios")
    chat.press("loc:riomayor")
    chat.press("loc:pozoluengo")
    chat.press("dia:2026-09-23")
    chat.state.update(origen="campoalto", destino="pinarnuevo")
    texto = cuerpo(chat.press("vuelta"))
    assert "no vendemos billetes" in texto and "No hay trayecto directo" not in texto


# ── Localidades pendientes (aldeas sin hora de paso) ────────────────────────────


def sin_trayecto_de_aldea(chat: Conversation) -> None:
    textos = [r.body for turn in chat.turns for r in turn.replies]
    assert not any("directo" in t and "Aldea" in t for t in textos)
    assert not any("No hay autobuses" in t for t in textos)


def test_pendiente_en_origen_ofrece_usar_ver(canal: ChannelType, datos_pendientes: Datos) -> None:
    chat = charla(canal, datos_pendientes)
    chat.send("hola")
    chat.press("menu_horarios")
    turn = chat.send("Aldea A")
    assert cuerpo(turn) == (
        "Algunos autobuses paran en Aldea A, a unos 4 minutos de Pueblo A, pero "
        "aún no tenemos su hora de paso."
    )
    assert ids_de(turn) == ["usar:pueblo-a", "escribir"]
    assert "origen" not in chat.state

    turn = chat.press("usar:pueblo-a")
    assert [r for r in turn.replies if isinstance(r, List)][-1].header == "🚌 Desde Pueblo A"
    assert set(ids_de(turn)) >= {"loc:pueblo-b", "loc:pueblo-c"}
    assert "loc:aldea-a" not in ids_de(turn)
    sin_trayecto_de_aldea(chat)


def test_pendiente_en_destino_ofrece_usar_ver(canal: ChannelType, datos_pendientes: Datos) -> None:
    chat = charla(canal, datos_pendientes)
    chat.send("hola")
    chat.press("menu_horarios")
    chat.press("loc:pueblo-a")
    turn = chat.send("Aldea Bonita")
    assert "a unos 7 minutos de Pueblo B" in cuerpo(turn)
    assert ids_de(turn) == ["usar:pueblo-b", "escribir"]
    assert chat.state["origen"] == "pueblo-a"

    turn = chat.press("usar:pueblo-b")
    assert [r for r in turn.replies if isinstance(r, List)][-1].header == "🚌 Pueblo A → Pueblo B"
    assert any(i.startswith("dia:") for i in ids_de(turn))
    sin_trayecto_de_aldea(chat)


def test_pendiente_otro_pueblo_repregunta(canal: ChannelType, datos_pendientes: Datos) -> None:
    chat = charla(canal, datos_pendientes)
    chat.send("hola")
    chat.press("menu_horarios")
    chat.send("Aldea A")
    turn = chat.press("escribir")
    assert "pueblo" in cuerpo(turn).lower()
    assert chat.state["step"] == "ESCRIBIR_ORIGEN"
    turn = chat.send("Pueblo B")
    assert [r for r in turn.replies if isinstance(r, List)][-1].header == "🚌 Desde Pueblo B"


def test_pendiente_desde_la_lista_de_candidatas(
    canal: ChannelType, datos_pendientes: Datos
) -> None:
    chat = charla(canal, datos_pendientes)
    chat.send("hola")
    chat.press("menu_horarios")
    assert ids_de(chat.send("aldea")) == ["loc:aldea-a", "loc:aldea-b"]
    assert ids_de(chat.press("loc:aldea-b")) == ["usar:pueblo-b", "escribir"]
    sin_trayecto_de_aldea(chat)


def test_pendiente_desde_una_errata_confirmada(canal: ChannelType, datos_pendientes: Datos) -> None:
    chat = charla(canal, datos_pendientes)
    chat.send("hola")
    chat.press("menu_horarios")
    assert ids_de(chat.send("aldeaa")) == ["si", "no"]
    assert ids_de(chat.press("si")) == ["usar:pueblo-a", "escribir"]
    assert chat.state["step"] == "SEL_ORIGEN"
    sin_trayecto_de_aldea(chat)


def test_pendiente_cuyo_ver_es_el_origen(canal: ChannelType, datos_pendientes: Datos) -> None:
    chat = charla(canal, datos_pendientes)
    chat.send("hola")
    chat.press("menu_horarios")
    chat.press("loc:pueblo-a")
    assert ids_de(chat.send("Aldea A")) == ["usar:pueblo-a", "escribir"]
    turn = chat.press("usar:pueblo-a")
    assert "Elige un destino distinto" in cuerpo(turn)
    assert chat.state["step"] == "SEL_DESTINO"


@pytest.mark.parametrize("valor", ["usar:no-existe", "usar:aldea-a"])
def test_usar_manipulado_repite_el_paso(
    canal: ChannelType, datos_pendientes: Datos, valor: str
) -> None:
    chat = charla(canal, datos_pendientes)
    chat.send("hola")
    chat.press("menu_horarios")
    turn = chat.press(valor, check=False)
    assert "loc:pueblo-a" in ids_de(turn)
    assert chat.state["step"] == "SEL_ORIGEN" and "origen" not in chat.state

    chat.press("loc:pueblo-a")
    turn = chat.press(valor, check=False)
    assert [r for r in turn.replies if isinstance(r, List)][-1].header == "🚌 Desde Pueblo A"
    assert chat.state["step"] == "SEL_DESTINO" and chat.state["origen"] == "pueblo-a"
    sin_trayecto_de_aldea(chat)


# ── Carrascal, un pueblo intermedio normal ──────────────────────────────────────


def test_carrascal_como_origen_es_un_pueblo_normal(canal: ChannelType) -> None:
    chat = charla(canal)
    chat.send("hola")
    chat.press("menu_horarios")
    turn = chat.send("Carrascal")
    assert [r for r in turn.replies if isinstance(r, List)][-1].header == "🚌 Desde Carrascal"
    assert chat.state["step"] == "SEL_DESTINO" and chat.state["origen"] == "carrascal"


def test_carrascal_como_destino_llega_al_resultado(canal: ChannelType) -> None:
    chat = charla(canal, now=cero("2026-09-23"))
    chat.send("hola")
    chat.press("menu_horarios")
    chat.press("loc:riomayor")
    turn = chat.send("Carrascal")
    assert [r for r in turn.replies if isinstance(r, List)][-1].header == "🚌 Riomayor → Carrascal"
    assert chat.state["step"] == "SEL_DIA" and chat.state["destino"] == "carrascal"
    turn = chat.press("dia:2026-09-23")
    assert len(turn.replies) == 1 and "Carrascal" in cuerpo(turn)
