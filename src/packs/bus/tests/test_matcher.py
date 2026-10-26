"""packs/bus/tests/test_matcher.py — reglas de coincidencia de texto,
contra `horarios/` real y una fixture pequeña para el límite de candidatas."""

from __future__ import annotations

import dataclasses
from pathlib import Path

from packs.bus import formato, loader, matcher

FIXTURES = Path(__file__).parent / "fixtures"
HORARIOS_REAL = FIXTURES / "horarios_real"


def _horarios_real() -> loader.Horarios:
    return loader.cargar(HORARIOS_REAL)


def _nombres(h: loader.Horarios, coincidencia: matcher.Coincidencia) -> list[str]:
    return [h.modelo.localidades[lid].nombre for lid in coincidencia.localidades]


# ── casos exactos, prefijo, alias ───────────────────────────────────────────


def test_exacto_alias_y_mayusculas() -> None:
    h = _horarios_real()
    m = matcher.Matcher(h)
    for texto in ("Pozoblanco", "POZOBLANCO", "pozo"):
        r = m.buscar(texto)
        assert r.tipo == "unico"
        assert _nombres(h, r) == ["Pozoblanco"]


def test_cordoba_exacto_no_arrastra_villanueva_de_cordoba() -> None:
    h = _horarios_real()
    m = matcher.Matcher(h)
    r = m.buscar("Córdoba")
    assert r.tipo == "unico"
    assert _nombres(h, r) == ["Córdoba"]


def test_prefijo_cor_elegir_cordoba_coronada() -> None:
    h = _horarios_real()
    m = matcher.Matcher(h)
    r = m.buscar("cor")
    assert r.tipo == "elegir"
    assert set(_nombres(h, r)) == {"Córdoba", "Coronada"}


def test_prefijo_fuente_elegir_cuatro() -> None:
    h = _horarios_real()
    m = matcher.Matcher(h)
    r = m.buscar("fuente")
    assert r.tipo == "elegir"
    assert set(_nombres(h, r)) == {
        "Fuente Carreteros",
        "Fuente La Lancha",
        "Fuente Obejuna",
        "Fuente Palmera",
    }


def test_prefijo_vil_elegir_nueve() -> None:
    h = _horarios_real()
    m = matcher.Matcher(h)
    r = m.buscar("vil")
    assert r.tipo == "elegir"
    assert len(r.localidades) == 9


def test_villanueva_elegir_tres_sin_estacion_ave() -> None:
    h = _horarios_real()
    r = matcher.Matcher(h).buscar("villanueva")
    assert r.tipo == "elegir"
    assert set(_nombres(h, r)) == {
        "Villanueva de Córdoba",
        "Villanueva del Duque",
        "Villanueva del Rey",
    }


def test_villanueva_de_cordoba_unico_y_estacion_unico() -> None:
    h = _horarios_real()
    m = matcher.Matcher(h)
    r = m.buscar("villanueva de cordoba")
    assert r.tipo == "unico"
    assert _nombres(h, r) == ["Villanueva de Córdoba"]
    r = m.buscar("estacion")
    assert r.tipo == "unico"
    assert _nombres(h, r) == ["Estación AVE Villanueva de Córdoba"]


def test_el_viso_el_vacar_santa_eufemia_pantano_unicos() -> None:
    h = _horarios_real()
    m = matcher.Matcher(h)
    esperado = {
        "el viso": "El Viso",
        "el vacar": "El Vacar",
        "santa eufemia": "Santa Eufemia",
        "pantano": "Pantano",
    }
    for texto, nombre in esperado.items():
        r = m.buscar(texto)
        assert r.tipo == "unico", texto
        assert _nombres(h, r) == [nombre], texto


def test_sta_eufemia_confirma_y_st_eufemia_no_coincide() -> None:
    h = _horarios_real()
    m = matcher.Matcher(h)
    r = m.buscar("sta eufemia")
    assert r.tipo == "confirmar"
    assert _nombres(h, r) == ["Santa Eufemia"]
    assert m.buscar("st eufemia").tipo == "sin_coincidencia"


def test_villanueva_duque_unico() -> None:
    h = _horarios_real()
    m = matcher.Matcher(h)
    for texto in ("villanueva duque", "Villanueva del Duque"):
        r = m.buscar(texto)
        assert r.tipo == "unico"
        assert _nombres(h, r) == ["Villanueva del Duque"]


def test_villafranca_siempre_pregunta() -> None:
    h = _horarios_real()
    m = matcher.Matcher(h)

    esperadas = {"Villafranca de Córdoba", "Villafranca de los Barros"}

    r = m.buscar("villafranca")
    assert r.tipo == "elegir"
    assert set(_nombres(h, r)) == esperadas

    r = m.buscar("villafranka")
    assert r.tipo == "elegir"  # nunca 'confirmar', aunque sea una errata
    assert set(_nombres(h, r)) == esperadas

    r = m.buscar("Villafranca de Córdoba")
    assert r.tipo == "unico"
    assert _nombres(h, r) == ["Villafranca de Córdoba"]


def test_errata_unica_confirma() -> None:
    h = _horarios_real()
    m = matcher.Matcher(h)

    r = m.buscar("pozoblnco")
    assert r.tipo == "confirmar"
    assert _nombres(h, r) == ["Pozoblanco"]

    r = m.buscar("zafar")
    assert r.tipo == "confirmar"
    assert _nombres(h, r) == ["Zafra"]


def test_errata_distancia_2_en_clave_corta_no_coincide() -> None:
    # 'zafra' tiene 5 letras (umbral <=1); una query a distancia 2 no debe
    # generar ninguna candidata.
    assert matcher.damerau("zabsa", "zafra") == 2
    h = _horarios_real()
    m = matcher.Matcher(h)
    r = m.buscar("zabsa")
    assert r.tipo == "sin_coincidencia"


def test_menos_de_minimo_letras_sin_exacto() -> None:
    h = _horarios_real()
    m = matcher.Matcher(h)
    for texto in ("po", "z"):
        r = m.buscar(texto)
        assert r.tipo == "sin_coincidencia"


def test_relleno_inicial_se_quita() -> None:
    h = _horarios_real()
    m = matcher.Matcher(h)

    r = m.buscar("desde pozoblanco")
    assert r.tipo == "unico"
    assert _nombres(h, r) == ["Pozoblanco"]

    r = m.buscar("a la herreria")
    assert r.tipo == "unico"
    assert _nombres(h, r) == ["La Herrería"]

    r = m.buscar("voy a cordoba")
    assert r.tipo == "unico"
    assert _nombres(h, r) == ["Córdoba"]


def test_relleno_inicial_con_puntuacion() -> None:
    h = _horarios_real()
    m = matcher.Matcher(h)
    for texto in ("¿desde pozoblanco?", "Desde, Pozoblanco", "¿Hacia Pozoblanco?"):
        r = m.buscar(texto)
        assert r.tipo == "unico", texto
        assert _nombres(h, r) == ["Pozoblanco"]


def test_mayusculas_tildes_y_espacios() -> None:
    h = _horarios_real()
    m = matcher.Matcher(h)
    for texto, esperado in (
        ("POZOBLANCO", "Pozoblanco"),
        ("  pOzObLaNcO  ", "Pozoblanco"),
        ("CÓRDOBA", "Córdoba"),
        ("cordoba", "Córdoba"),
        ("PENARROYA", "Peñarroya-Pueblonuevo"),
        ("peñarroya pueblonuevo", "Peñarroya-Pueblonuevo"),
        ("BELALCÁZAR", "Belalcázar"),
    ):
        r = m.buscar(texto)
        assert r.tipo == "unico", texto
        assert _nombres(h, r) == [esperado], texto


def test_nombre_de_parada_exacto() -> None:
    h = _horarios_real()
    m = matcher.Matcher(h)
    r = m.buscar("Pozoblanco (Hospital)")
    assert r.tipo == "unico"
    assert _nombres(h, r) == ["Pozoblanco"]


def test_alias_el_cruce() -> None:
    h = _horarios_real()
    m = matcher.Matcher(h)
    r = m.buscar("el cruce")
    assert r.tipo == "unico"
    assert _nombres(h, r) == ["Cruce de Villaharta"]


def test_sin_coincidencia() -> None:
    h = _horarios_real()
    m = matcher.Matcher(h)
    for texto in ("pozoblanco cordoba", "xyz", "la", ""):
        r = m.buscar(texto)
        assert r.tipo == "sin_coincidencia"


def test_sin_alias_no_reconocido() -> None:
    # 'pueblonuevo' y 'obejuna' solo se reconocerían con alias (P13); hoy no
    # existen.
    h = _horarios_real()
    m = matcher.Matcher(h)
    for texto in ("pueblonuevo", "obejuna"):
        r = m.buscar(texto)
        assert r.tipo == "sin_coincidencia"


# ── límite de candidatas (9 -> elegir, 10 -> demasiadas) ────────────────────


def test_limite_9_elegir_10_demasiadas() -> None:
    h = loader.cargar(FIXTURES / "horarios_matcher")
    m = matcher.Matcher(h)

    r10 = m.buscar("prefijotest")
    assert r10.tipo == "demasiadas"
    assert len(r10.localidades) == 10

    # Quitamos una localidad del modelo para probar el límite justo en 9.
    localidades_9 = dict(h.modelo.localidades)
    quitada = next(iter(localidades_9))
    del localidades_9[quitada]
    modelo_9 = dataclasses.replace(h.modelo, localidades=localidades_9)
    h_9 = dataclasses.replace(h, modelo=modelo_9)
    m_9 = matcher.Matcher(h_9)
    r9 = m_9.buscar("prefijotest")
    assert r9.tipo == "elegir"
    assert len(r9.localidades) == 9


def test_localidad_no_usada_se_encuentra_pero_no_sale_en_lineas() -> None:
    h = loader.cargar(FIXTURES / "horarios_matcher")
    m = matcher.Matcher(h)
    r = m.buscar("Prefijotest Uno")
    assert r.tipo == "unico"
    assert _nombres(h, r) == ["Prefijotest Uno"]
    assert matcher.lineas(h) == ()  # esta fixture no tiene ninguna línea


# ── lineas() sobre horarios/ real ───────────────────────────────────────────


def test_zonas_ya_no_existe() -> None:
    assert not hasattr(matcher, "zonas")


def test_lineas_reales_en_orden_de_titulo_con_pueblos_ordenados() -> None:
    h = _horarios_real()
    ls = matcher.lineas(h)
    assert len(ls) == 15
    titulos = [formato.normalizar(linea.titulo) for linea, _ in ls]
    assert titulos == sorted(titulos)
    assert [linea.id for linea, _ in ls] == list(h.lineas_pueblos)
    for _linea, localidades in ls:
        nombres_norm = [formato.normalizar(loc.nombre) for loc in localidades]
        assert nombres_norm == sorted(nombres_norm)
        assert localidades  # sin líneas vacías
        for loc in localidades:
            assert loc.id in h.localidad_viajes
            assert loc.pendiente is None


def test_rivero_y_los_mochos_son_pueblos_normales_y_vecinas() -> None:
    h = _horarios_real()
    m = matcher.Matcher(h)
    esperado = {
        "los mochos": ["Los Mochos"],
        "rivero": ["Rivero de Posadas"],
        "posadas": ["Posadas"],
        "blazquez": ["Los Blázquez"],
        "granja": ["Granja de Torrehermosa"],
    }
    for texto, nombres in esperado.items():
        r = m.buscar(texto)
        assert r.tipo == "unico", texto
        assert _nombres(h, r) == nombres, texto
    assert m.buscar("los mochos").localidades == ("los-mochos",)
    assert m.buscar("rivero").localidades == ("rivero-de-posadas",)
    assert m.buscar("blazquez").localidades == ("los-blazquez",)


def test_lineas_pendientes_no_aparecen_en_ninguna_linea() -> None:
    h = loader.cargar(FIXTURES / "horarios_pendientes")
    ids = {loc.id for _, locs in matcher.lineas(h) for loc in locs}
    assert "aldea-a" not in ids
    assert "aldea-b" not in ids
    assert {"pueblo-a", "pueblo-b", "pueblo-c"} <= ids


# ── propiedad: cada localidad real, escrita con su nombre exacto ───────────


def test_propiedad_toda_localidad_por_su_nombre_exacto() -> None:
    # El nombre oficial completo de cada localidad es único incluso para el
    # par Villafranca (de Córdoba / de los Barros): la ambigüedad declarada
    # solo salta al escribir el alias compartido "villafranca" (ver
    # test_villafranca_siempre_pregunta), nunca al escribir el nombre
    # completo ("Villafranca de Córdoba" resuelve sola).
    h = _horarios_real()
    m = matcher.Matcher(h)
    for lid, loc in h.modelo.localidades.items():
        r = m.buscar(loc.nombre)
        assert r.tipo == "unico", f"{lid}: se esperaba 'unico', fue {r.tipo}"
        assert r.localidades == (lid,)


# ── Localidades pendientes (ciclo C2, P15/P32) ───────────────────────────────


def test_localidades_pendientes_se_encuentran_por_texto() -> None:
    h = loader.cargar(FIXTURES / "horarios_pendientes")
    m = matcher.Matcher(h)

    r = m.buscar("Aldea A")  # exacto
    assert (r.tipo, r.localidades) == ("unico", ("aldea-a",))

    r = m.buscar("aldea bon")  # prefijo
    assert (r.tipo, r.localidades) == ("unico", ("aldea-b",))

    r = m.buscar("aldeaa")  # errata
    assert (r.tipo, r.localidades) == ("confirmar", ("aldea-a",))

    r = m.buscar("aldea")  # varias, en orden alfabético
    assert (r.tipo, r.localidades) == ("elegir", ("aldea-a", "aldea-b"))


def test_pueblo_a_nunca_devuelve_aldea_a() -> None:
    h = loader.cargar(FIXTURES / "horarios_pendientes")
    m = matcher.Matcher(h)
    r = m.buscar("pueblo a")
    assert (r.tipo, r.localidades) == ("unico", ("pueblo-a",))
