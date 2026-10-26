"""Escenarios obligatorios del pack `bus`, con el arnés de
conversación en los dos tipos de canal. Cada respuesta pasa por los límites
comunes y por el renderizado de los dos adaptadores. Los datos son los
reales congelados (`fixtures/horarios_real/`) salvo donde se indica.

La consulta completa por el bot de pruebas, de extremo a extremo, está en
`tests/integration/test_bus_pack.py`."""

from __future__ import annotations

import logging
from datetime import date

import pytest

from core.replies import Buttons, List, Text
from core.testing import Conversation
from core.testing.harness import ChannelType, Turn
from packs.bus import query
from packs.bus.datos import Datos
from packs.bus.pack import pack
from packs.bus.tests.compat import CONFIG, datos_reales

MIERCOLES = "2026-09-23T10:00:00+02:00"  # laborable, dentro de la vigencia
MENU = ["🚌 Ver horarios", "ℹ️ Contacto"]
RESULTADO = ["📅 Otro día", "🔄 Ver la vuelta", "🔍 Otra consulta"]


@pytest.fixture(params=["whatsapp", "telegram"])
def canal(request: pytest.FixtureRequest) -> ChannelType:
    return request.param  # type: ignore[no-any-return]


def charla(canal: ChannelType, datos: Datos | None = None, now: str = MIERCOLES) -> Conversation:
    return Conversation(pack, config=CONFIG, data=datos or datos_reales(), channel=canal, now=now)


def hasta_dias(chat: Conversation) -> Turn:
    """Pozoblanco → Córdoba, hasta la lista de días."""
    chat.send("hola").expect(buttons=MENU)
    chat.press("menu_horarios").expect(list_includes="Pozoblanco")
    chat.press("loc:pozoblanco")
    return chat.press("loc:cordoba")


def cuerpo(turn: Turn) -> str:
    return "\n\n".join(r.body for r in turn.replies)


# ── Camino feliz ──────────────────────────────────────────────────────────


def test_consulta_completa(canal: ChannelType) -> None:
    chat = charla(canal)
    dias = hasta_dias(chat)
    lista = dias.replies[-1]
    assert isinstance(lista, List) and lista.header == "🚌 Pozoblanco → Córdoba"
    ids = [r.id for s in lista.sections for r in s.rows]
    assert ids == [f"dia:2026-09-{d}" for d in range(23, 30)] + ["otra_fecha"]

    turn = chat.press("dia:2026-09-24").expect(buttons=RESULTADO)
    texto = cuerpo(turn)
    assert texto.startswith("🚌 Pozoblanco → Córdoba\n📅 Jueves 24/09")
    esperadas = query.consultar(datos_reales().horarios, "pozoblanco", "cordoba", date(2026, 9, 24))
    assert esperadas.estado == "con_salidas"
    for salida in esperadas.salidas:
        assert f"{salida.hora_salida:%H:%M} → {salida.hora_llegada:%H:%M}" in texto
    assert chat.state == {
        "step": "RESULTADO",
        "origen": "pozoblanco",
        "destino": "cordoba",
        "fecha": "2026-09-24",
    }


def test_ver_la_vuelta(canal: ChannelType) -> None:
    chat = charla(canal)
    hasta_dias(chat)
    chat.press("dia:2026-09-24")
    turn = chat.press("vuelta").expect(list_includes="📅 Otra fecha")
    lista = turn.replies[-1]
    assert isinstance(lista, List) and lista.header == "🚌 Córdoba → Pozoblanco"
    chat.press("dia:2026-09-24").expect(text_contains="🚌 Córdoba → Pozoblanco", buttons=RESULTADO)


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
    assert "📞 Teléfono: 957 42 90 30" in texto
    assert "lunes a miércoles laborables de 08:00 a 15:00 y de 17:00 a 19:00" in texto
    # `HttpUrl` normaliza una URL sin ruta con la barra final.
    assert texto.endswith("🌐 Web: https://www.autocaressansebastian.es/")


# ── Días sin salidas ──────────────────────────────────────────────────────


def test_dia_sin_servicio_ofrece_el_siguiente_dia(canal: ChannelType) -> None:
    chat = charla(canal)
    chat.send("hola")
    chat.press("menu_horarios")
    chat.send("Ochavillos")  # no está en el menú de inicio: se escribe
    chat.press("loc:cordoba")
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
    assert "📞 957 42 90 30 (horario de oficina:" in texto


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
    chat.press("loc:cordoba")
    turn = chat.send("Alcolea")
    assert "no vendemos billetes" in cuerpo(turn)
    assert chat.state["step"] == "SEL_DESTINO"


def test_sin_trayecto_directo(canal: ChannelType) -> None:
    chat = charla(canal)
    chat.send("hola")
    chat.press("menu_horarios")
    chat.press("loc:pozoblanco")
    turn = chat.send("Badajoz")
    assert "No hay trayecto directo de Pozoblanco a Badajoz." in cuerpo(turn)
    assert "📞 957 42 90 30" in cuerpo(turn)


def test_origen_igual_a_destino(canal: ChannelType) -> None:
    chat = charla(canal)
    chat.send("hola")
    chat.press("menu_horarios")
    chat.press("loc:pozoblanco")
    turn = chat.send("pozoblanco")
    assert "Elige un destino distinto." in cuerpo(turn)
    assert chat.state["step"] == "SEL_DESTINO"


@pytest.mark.parametrize("texto", ["villafranca", "villafranka"])
def test_villafranca_siempre_pregunta(canal: ChannelType, texto: str) -> None:
    chat = charla(canal)
    chat.send("hola")
    chat.press("menu_horarios")
    turn = chat.send(texto).expect(
        list_includes="Villafranca de Córdoba"
    )  # 22 letras: no caben en un botón, va en lista
    lista = turn.replies[-1]
    assert isinstance(lista, List)
    ids = {r.id for s in lista.sections for r in s.rows}
    assert {"loc:villafranca-de-cordoba", "loc:villafranca-de-los-barros"} <= ids
    chat.press("loc:villafranca-de-cordoba").expect(text_contains="¿A dónde vas?")


def test_errata_confirmada(canal: ChannelType) -> None:
    chat = charla(canal)
    chat.send("hola")
    chat.press("menu_horarios")
    chat.send("pozoblnco").expect(text="¿Querías decir Pozoblanco?", buttons=["Sí", "No"])
    turn = chat.press("si")
    lista = turn.replies[-1]
    assert isinstance(lista, List) and lista.header == "🚌 Desde Pozoblanco"


def test_errata_rechazada(canal: ChannelType) -> None:
    chat = charla(canal)
    chat.send("hola")
    chat.press("menu_horarios")
    chat.send("pozoblnco")
    chat.press("no").expect(text="Vale, escríbelo de otra forma.")
    assert chat.state["step"] == "ESCRIBIR_ORIGEN"
    chat.send("Pozoblanco").expect(text_contains="¿A dónde vas?")


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
    assert registro.getMessage() == "[NO_RECONOCIDO] paso=origen texto=<numero>"
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
    assert "salidas más, llama al 957 42 90 30." in texto.body
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
