"""packs/bus/tests/test_interactive.py — ninguna lista supera 10 filas ni ningún botón
3. La prueba más importante: la lista de destinos depende
del origen elegido y nunca puede pasarse del límite."""

from typing import Any

from packs.bus import conversation as flujo
from packs.bus import interactive as I
from packs.bus import matcher, query
from packs.bus.datos import Datos
from packs.bus.interactive import descripcion_linea
from packs.bus.modelo import Linea, Localidad
from tests.packs.bus.conversation_harness import CONFIG, NEGOCIO_TELEFONO, datos_demo, wa, wa_all

# Los constructores sin la config y el payload de WhatsApp que leen estos tests.


def build_menu() -> dict[str, Any]:
    return wa(I.build_menu(CONFIG))


def build_info() -> dict[str, Any]:
    return wa(I.build_info(CONFIG))


def build_origen(
    localidades: list[tuple[str, str]], aviso: str | None = None, con_lineas: bool = False
) -> dict[str, Any]:
    return wa(I.build_origen(CONFIG, localidades, aviso=aviso, con_lineas=con_lineas))


def build_destinos(
    origen_nombre: str,
    destinos: list[tuple[str, str]],
    aviso: str | None = None,
    con_lineas: bool = False,
) -> dict[str, Any]:
    return wa(I.build_destinos(CONFIG, origen_nombre, destinos, aviso=aviso, con_lineas=con_lineas))


def build_candidatas(localidades: list[tuple[str, str]], campo: str) -> dict[str, Any]:
    return wa(I.build_candidatas(CONFIG, localidades))


def build_confirmar(nombre: str) -> dict[str, Any]:
    return wa(I.build_confirmar(CONFIG, nombre))


def build_escribir(campo: str, texto: str) -> dict[str, Any]:
    return wa(I.build_escribir(CONFIG, campo, texto))


def build_dias(
    origen: str, destino: str, filas: list[tuple[str, str, str]], aviso: str | None = None
) -> dict[str, Any]:
    return wa(I.build_dias(CONFIG, origen, destino, filas, aviso=aviso))


def build_resultado(texto: str, botones: list[tuple[str, str]]) -> dict[str, Any]:
    return wa_all(I.build_resultado(CONFIG, texto, botones))


def build_localidad_pendiente(
    texto: str, ver_id: str, ver_nombre: str, campo: str
) -> dict[str, Any]:
    return wa(I.build_localidad_pendiente(CONFIG, texto, ver_id, ver_nombre))


def build_lineas(lineas: list[tuple[Linea, int]], pagina: int, campo: str) -> dict[str, Any]:
    return wa(I.build_lineas(CONFIG, lineas, pagina, campo))


def build_linea(linea: Linea, pueblos: list[tuple[str, str]], pagina: int) -> dict[str, Any]:
    return wa(I.build_linea(CONFIG, linea, pueblos, pagina))


MAX_ROWS = 10
MAX_BUTTONS = 3
MAX_ROW_TITLE = 24
MAX_ROW_DESC = 72
MAX_BUTTON_TITLE = 20


def _rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    sections = payload["interactive"]["action"]["sections"]
    return [row for section in sections for row in section["rows"]]


def _buttons(payload: dict[str, Any]) -> list[dict[str, Any]]:
    buttons: list[dict[str, Any]] = payload["interactive"]["action"]["buttons"]
    return buttons


def _assert_list_limits(payload: dict[str, Any]) -> None:
    assert payload["interactive"]["type"] == "list"
    rows = _rows(payload)
    assert len(rows) <= MAX_ROWS, f"{len(rows)} rows > {MAX_ROWS}"
    for row in rows:
        assert len(row["title"]) <= MAX_ROW_TITLE
        if "description" in row:
            assert len(row["description"]) <= MAX_ROW_DESC


def _assert_button_limits(payload: dict[str, Any]) -> None:
    assert payload["interactive"]["type"] == "button"
    buttons = _buttons(payload)
    assert len(buttons) <= MAX_BUTTONS
    for b in buttons:
        assert len(b["reply"]["title"]) <= MAX_BUTTON_TITLE


def test_menu_within_limits() -> None:
    _assert_button_limits(build_menu())


def test_menu_boton_contacto_sin_recorte() -> None:
    titulos = {b["reply"]["id"]: b["reply"]["title"] for b in _buttons(build_menu())}
    assert titulos["menu_info"] == "ℹ️ Contacto"
    assert len(titulos["menu_info"]) <= MAX_BUTTON_TITLE


def test_info_within_limits() -> None:
    _assert_button_limits(build_info())


def test_build_origen_within_limits() -> None:
    datos = datos_demo()
    localidades = [
        (lid, datos.horarios.modelo.localidades[lid].nombre) for lid in datos.menu_origen
    ]
    _assert_list_limits(build_origen(localidades))
    _assert_list_limits(build_origen(localidades, con_lineas=True))


def test_build_destinos_every_real_origin_within_limits() -> None:
    """Propiedad obligatoria (plan fase 4): recorre TODOS los orígenes
    reales de horarios/ y comprueba que la lista de destinos nunca supera
    el límite de WhatsApp, sea cual sea su longitud."""
    datos = datos_demo()
    horarios = datos.horarios
    for origen_id in horarios.localidad_viajes:
        alcanzables = list(query.destinos_desde(horarios, origen_id))
        if not alcanzables:
            continue
        nombres = {lid: horarios.modelo.localidades[lid].nombre for lid in alcanzables}
        prioridad = list(datos.menu_origen)
        ordenados = flujo.ordenar_destinos(alcanzables, prioridad, nombres)
        origen_nombre = horarios.modelo.localidades[origen_id].nombre
        payload = build_destinos(origen_nombre, ordenados)
        _assert_list_limits(payload)


def test_build_candidatas_within_limits() -> None:
    datos = datos_demo()
    localidades = [
        (lid, datos.horarios.modelo.localidades[lid].nombre)
        for lid in list(datos.horarios.modelo.localidades)[:9]
    ]
    payload = build_candidatas(localidades, "origen")
    if payload["interactive"]["type"] == "list":
        _assert_list_limits(payload)
    else:
        _assert_button_limits(payload)


def test_build_confirmar_within_limits() -> None:
    _assert_button_limits(build_confirmar("Pozoluengo"))


def test_build_escribir_within_limits() -> None:
    _assert_button_limits(build_escribir("origen", "texto"))


def _lineas_reales() -> tuple[tuple[Linea, tuple[Localidad, ...]], ...]:
    datos = datos_demo()
    return matcher.lineas(datos.horarios)


def _titulo_utf16(texto: str) -> int:
    return len(texto.encode("utf-16-le")) // 2


def _assert_titulos_whatsapp(payload: dict[str, Any]) -> None:
    """El título de fila se cuenta en code points y en unidades UTF-16."""
    for row in _rows(payload):
        assert len(row["title"]) <= MAX_ROW_TITLE
        assert _titulo_utf16(row["title"]) <= MAX_ROW_TITLE, row["title"]


def _linea_falsa(n: int, nombre_corto: str | None = None, nombre: str | None = None) -> Linea:
    return Linea(
        id=f"linea-{n:02d}",
        nombre=nombre or f"Linea {n:02d}",
        telefono_demanda=None,
        avisos=(),
        no_circula=(),
        temporadas=(),
        nombre_corto=nombre_corto,
    )


def test_build_lineas_ficticias_within_limits() -> None:
    todas = [(linea, len(locs)) for linea, locs in _lineas_reales()]
    assert len(todas) == 8
    # Las 8 líneas ficticias caben en una sola página: 8 + volver = 9 filas.
    for campo in ("origen", "destino"):
        payload = build_lineas(todas, 0, campo)
        _assert_list_limits(payload)
        _assert_titulos_whatsapp(payload)
        assert len(_rows(payload)) == 9
    ids = [r["id"] for r in _rows(build_lineas(todas, 0, "origen"))]
    assert ids[-1] == "menu"
    ids = [r["id"] for r in _rows(build_lineas(todas, 0, "destino"))]
    assert ids[-1] == "cambiar_origen"


def test_build_lineas_pagina_0_con_mas_lineas_son_10_filas() -> None:
    lineas = [(_linea_falsa(n), 3) for n in range(1, 10)]  # 9: hay una página más
    rows = _rows(build_lineas(lineas, 0, "origen"))
    assert len(rows) == 10
    assert rows[8] == {"id": "lineas:1", "title": "➡️ Más líneas"}
    assert rows[9]["id"] == "menu"
    assert rows[0]["id"] == "linea:linea-01:0"


def test_build_lineas_15_lineas_dos_paginas(datos_muchas_lineas: Datos) -> None:
    todas = [(linea, len(locs)) for linea, locs in matcher.lineas(datos_muchas_lineas.horarios)]
    assert len(todas) == 12
    p0 = build_lineas(todas, 0, "origen")
    p1 = build_lineas(todas, 1, "origen")
    assert len(_rows(p0)) == 10
    assert len(_rows(p1)) == 4 + 1  # 4 líneas + volver
    _assert_list_limits(p0)
    _assert_list_limits(p1)
    _assert_titulos_whatsapp(p0)
    _assert_titulos_whatsapp(p1)
    assert _rows(p0)[8]["id"] == "lineas:1"
    assert _rows(p1)[-1]["id"] == "menu"
    assert all(r["id"] != "lineas:2" for r in _rows(p1))


def test_build_lineas_nombre_corto_en_titulo_y_descripcion() -> None:
    linea = _linea_falsa(
        1,
        nombre_corto="Ruta del norte",
        nombre="Ruta muy larga del norte al sur de la sierra",
    )
    fila = _rows(build_lineas([(linea, 2)], 0, "origen"))[0]
    assert fila["title"] == "Ruta del norte"
    assert fila["description"] == ("Ruta muy larga del norte al sur de la sierra · 2 pueblos")


def test_descripcion_linea_singular_y_sin_nombre_corto() -> None:
    assert descripcion_linea(_linea_falsa(1), 1) == "1 pueblo"
    assert descripcion_linea(_linea_falsa(1), 5) == "5 pueblos"
    fila = _rows(build_lineas([(_linea_falsa(1), 1)], 0, "origen"))[0]
    assert fila["description"] == "1 pueblo"


def test_descripcion_linea_nombre_largo_no_come_el_recuento() -> None:
    linea = _linea_falsa(1, nombre_corto="Corta", nombre="X" * 200)
    desc = descripcion_linea(linea, 12)
    assert len(desc) <= MAX_ROW_DESC
    assert desc.endswith(" · 12 pueblos")
    fila = _rows(build_lineas([(linea, 12)], 0, "destino"))[0]
    assert fila["description"] == desc


def test_build_linea_20_pueblos_3_paginas(datos_muchas_lineas: Datos) -> None:
    larga, locs = next(
        (li, lo)
        for li, lo in matcher.lineas(datos_muchas_lineas.horarios)
        if li.id == "linea-larga"
    )
    assert len(locs) == 19  # origen + 18
    filas = [(loc.id, loc.nombre) for loc in locs]
    for n, n_pueblos in enumerate((8, 8, 3)):
        hay_mas = n < 2
        payload = build_linea(larga, filas, n)
        assert len(_rows(payload)) == n_pueblos + (2 if hay_mas else 1)
        _assert_list_limits(payload)
        _assert_titulos_whatsapp(payload)
        rows = _rows(payload)
        assert rows[-1]["id"] == "lineas:0"
        if hay_mas:
            assert rows[-2]["id"] == f"linea:linea-larga:{n + 1}"
        assert len(rows) <= 10
        assert payload["interactive"]["header"]["text"] == "🚌 Linea Larga"


def test_build_linea_titulo_corto_en_cabecera_y_seccion() -> None:
    linea = _linea_falsa(
        1,
        nombre_corto="Ruta del norte",
        nombre="Ruta muy larga del norte al sur de la sierra",
    )
    payload = build_linea(linea, [("a", "Aldea")], 0)
    assert payload["interactive"]["header"]["text"] == "🚌 Ruta del norte"
    assert payload["interactive"]["action"]["sections"][0]["title"] == "Ruta del norte"


def test_build_escribir_boton_ver_por_linea() -> None:
    for campo in ("origen", "destino"):
        botones = _buttons(build_escribir(campo, "texto"))
        assert botones[0]["reply"]["id"] == "lineas:0"
        assert botones[0]["reply"]["title"] == "🚌 Ver por línea"
        assert len(botones) <= MAX_BUTTONS


def test_filas_ver_pueblos_por_linea_en_origen_y_destino() -> None:
    datos = datos_demo()
    localidades = [
        (lid, datos.horarios.modelo.localidades[lid].nombre) for lid in datos.menu_origen
    ]
    rows = _rows(build_origen(localidades, con_lineas=True))
    assert {"id": "lineas:0", "title": "🚌 Ver pueblos por línea"} in rows
    _assert_titulos_whatsapp(build_origen(localidades, con_lineas=True))
    nombres = [(f"x{i}", f"Pueblo {i}") for i in range(12)]
    payload = build_destinos("Origen", nombres, con_lineas=True)
    assert {"id": "lineas:0", "title": "🚌 Ver pueblos por línea"} in _rows(payload)
    _assert_list_limits(payload)
    _assert_titulos_whatsapp(payload)


def test_build_dias_within_limits() -> None:
    filas = [(f"dia:2026-09-{20 + i}", f"Fila {i}", "5 salidas") for i in range(7)]
    _assert_list_limits(build_dias("Pozoluengo", "Riomayor", filas))


def test_build_resultado_within_limits() -> None:
    botones = [
        ("otro_dia", "📅 Otro día"),
        ("vuelta", "🔄 Ver la vuelta"),
        ("otra_consulta", "🔍 Otra consulta"),
    ]
    _assert_button_limits(build_resultado("texto", botones))


def test_truncated_locality_names_keep_full_name_in_description() -> None:
    nombre_largo = "Villagrande del Soto muy largo de verdad para forzar el truncado"
    payload = build_origen([("villagrande-del-soto", nombre_largo)])
    fila = _rows(payload)[0]
    assert len(fila["title"]) <= MAX_ROW_TITLE
    assert fila["description"] == nombre_largo[:MAX_ROW_DESC]


def test_msg_resultado_truncates_at_4096_chars() -> None:
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
            notas=(f"Nota número {i} bastante larga para forzar el truncado.",),
        )
        for i in range(200)
    )
    consulta = Consulta(
        estado="con_salidas",
        salidas=salidas,
        info_dia=InfoDia(
            fecha=__import__("datetime").date(2026, 9, 23),
            dia_semana="miercoles",
            clase_dia="miercoles",
            es_festivo=False,
            nombre_festivo=None,
            es_lectivo=True,
            mes=9,
        ),
        temporadas=(),
        lineas_sin_datos=(),
        fuera_de_calendario=False,
        siguiente_con_servicio=None,
    )
    datos = datos_demo()
    texto = msg_resultado(
        CONFIG,
        consulta,
        datos.horarios,
        "Pozoluengo",
        "Riomayor",
        __import__("datetime").date(2026, 9, 23),
    )
    assert len(texto) <= 4096
    assert "más, llama al" in texto


def test_msg_resultado_sin_servicio_general_sin_siguiente_da_hecho_y_telefono() -> None:
    from datetime import date

    from packs.bus import calendario as cal
    from packs.bus.messages import msg_resultado
    from packs.bus.query import Consulta

    datos = datos_demo()
    calendario_de_datos = datos.horarios.modelo.calendario
    assert calendario_de_datos is not None
    fecha = date(2027, 12, 25)
    consulta = Consulta(
        estado="sin_servicio",
        salidas=(),
        info_dia=cal.info_dia(calendario_de_datos, fecha, permitir_fuera_de_vigencia=True),
        temporadas=(),
        lineas_sin_datos=(),
        fuera_de_calendario=False,
        siguiente_con_servicio=None,
        sin_servicio_general=True,
    )
    texto = msg_resultado(CONFIG, consulta, datos.horarios, "Pozoluengo", "Riomayor", fecha)
    assert "El 25/12 no hay servicio en ninguna línea" in texto
    assert NEGOCIO_TELEFONO in texto
    assert "próximos días" not in texto
    assert "festivo" not in texto  # sin nombre cargado, la cabecera es solo el día


def test_lista_de_destinos_con_no_vendibles_filtrados_respeta_limites() -> None:
    datos = datos_demo()
    horarios = datos.horarios
    for origen_id in ("riomayor", "campoalto", "pinarnuevo"):
        alcanzables = list(query.destinos_desde(horarios, origen_id))
        assert alcanzables
        for otro in ("riomayor", "campoalto", "pinarnuevo"):
            if otro != origen_id:
                assert otro not in alcanzables
        nombres = {lid: horarios.modelo.localidades[lid].nombre for lid in alcanzables}
        ordenados = flujo.ordenar_destinos(alcanzables, list(datos.menu_origen), nombres)
        payload = build_destinos(horarios.modelo.localidades[origen_id].nombre, ordenados)
        _assert_list_limits(payload)
        assert len(_rows(payload)) <= MAX_ROWS


# ── Fase 1b-1: origen con más de 9 destinos (paginación, P18) ───────────────

NOMBRE_LARGO = "Estación Grande de Villagrande del Soto"


def test_destinos_de_origen_con_30_aldeas_son_10_filas_con_las_8_esperadas(
    datos_muchas_lineas: Datos,
) -> None:
    horarios = datos_muchas_lineas.horarios
    alcanzables = list(query.destinos_desde(horarios, "origen"))
    assert len(alcanzables) > 9
    nombres = {lid: horarios.modelo.localidades[lid].nombre for lid in alcanzables}
    ordenados = flujo.ordenar_destinos(alcanzables, list(datos_muchas_lineas.menu_origen), nombres)
    payload = build_destinos("Origen", ordenados)
    _assert_list_limits(payload)
    filas = _rows(payload)
    assert len(filas) == 10
    assert [f["title"] for f in filas[:8]] == [
        "Aldea 01",
        "Aldea 02",
        "Aldea 03",
        "Aldea 04",
        "Aldea 05",
        "Aldea 06",
        "Aldea 07",
        "Aldea 08",
    ]
    assert [f["id"] for f in filas[8:]] == ["escribir", "cambiar_origen"]


def test_nombre_largo_estacion_ave_respeta_limites_en_todos_los_constructores() -> None:
    assert len(NOMBRE_LARGO) > MAX_ROW_TITLE
    fila = _rows(build_origen([("estacion-grande", NOMBRE_LARGO)]))[0]
    assert len(fila["title"]) <= MAX_ROW_TITLE
    assert fila["description"] == NOMBRE_LARGO

    _assert_button_limits(build_confirmar(NOMBRE_LARGO))

    # nombre largo: build_candidatas pasa de botones a lista
    cands = build_candidatas(
        [
            ("estacion-grande", NOMBRE_LARGO),
            ("villagrande-del-soto", "Villagrande"),
        ],
        "destino",
    )
    _assert_list_limits(cands)
    assert NOMBRE_LARGO in [r.get("description") for r in _rows(cands)]

    _assert_list_limits(
        build_dias("Pozoluengo", NOMBRE_LARGO, [("dia:2026-10-01", "Jueves 1", "2 salidas")])
    )


# ── Localidad pendiente (ciclo C2, P15/P32) ──────────────────────────────


def test_build_localidad_pendiente_within_limits() -> None:
    for nombre in (
        "Pozoluengo",
        "Montealto del Risco",
        "Villagrande de Riomayor",
        "Villagrande del Soto",
        "Fuenteclara del Norte",
    ):
        payload = build_localidad_pendiente("Texto", "ver-id", nombre, "origen")
        _assert_button_limits(payload)
        ids = [b["reply"]["id"] for b in _buttons(payload)]
        assert ids == ["usar:ver-id", "escribir"]


def test_build_localidad_pendiente_acorta_nombre_largo() -> None:
    def titulo(nombre: str) -> str:
        p = build_localidad_pendiente("t", "x", nombre, "destino")
        return str(_buttons(p)[0]["reply"]["title"])

    assert titulo("Pozoluengo") == "Usar Pozoluengo"
    assert titulo("Montealto del Risco") == "Usar Montealto"
    assert titulo("Villagrande de Riomayor") == "Usar Villagrande"
    assert titulo("Superextraordinariamente") == "Usar Superextraordin"


def test_build_localidad_pendiente_aldea_bonita_fixture(datos_pendientes: Datos) -> None:
    modelo = datos_pendientes.horarios.modelo
    aldea = modelo.localidades["aldea-b"]
    assert aldea.ver is not None
    ver = modelo.localidades[aldea.ver]
    payload = build_localidad_pendiente("Texto", aldea.ver, ver.nombre, "origen")
    _assert_button_limits(payload)
    titulos = [b["reply"]["title"] for b in _buttons(payload)]
    assert titulos[0] == "Usar Pueblo B"
    assert len(titulos[0]) <= 20


def test_datos_demo_no_tienen_localidades_pendientes() -> None:
    modelo = datos_demo().horarios.modelo
    assert all(loc.pendiente is None for loc in modelo.localidades.values())
