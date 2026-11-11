"""packs/bus/tests/test_matcher.py — reglas de coincidencia de texto,
contra `horarios_ficticios/` (red inventada, sin relación con ninguna red
real) y una fixture pequeña para el límite de candidatas."""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from packs.bus import formato, loader, matcher

FIXTURES = Path(__file__).parent / "fixtures"
HORARIOS_FICTICIOS = FIXTURES / "horarios_ficticios"


def _horarios() -> loader.Horarios:
    return loader.cargar(HORARIOS_FICTICIOS)


def _nombres(h: loader.Horarios, coincidencia: matcher.Coincidencia) -> list[str]:
    return [h.modelo.localidades[lid].nombre for lid in coincidencia.localidades]


# ── casos exactos, prefijo, alias ───────────────────────────────────────────


def test_exacto_alias_y_mayusculas() -> None:
    h = _horarios()
    m = matcher.Matcher(h)
    for texto in ("Pozoluengo", "POZOLUENGO", "pozo"):
        r = m.buscar(texto)
        assert r.tipo == "unico"
        assert _nombres(h, r) == ["Pozoluengo"]


def test_riomayor_exacto_no_arrastra_villagrande() -> None:
    h = _horarios()
    m = matcher.Matcher(h)
    r = m.buscar("Riomayor")
    assert r.tipo == "unico"
    assert _nombres(h, r) == ["Riomayor"]


def test_prefijo_rio_elegir_riomayor_riofondo() -> None:
    h = _horarios()
    m = matcher.Matcher(h)
    r = m.buscar("rio")
    assert r.tipo == "elegir"
    assert set(_nombres(h, r)) == {"Riomayor", "Riofondo"}


def test_villagrande_elegir_las_dos() -> None:
    h = _horarios()
    r = matcher.Matcher(h).buscar("villagrande")
    assert r.tipo == "elegir"
    assert set(_nombres(h, r)) == {"Villagrande de Riomayor", "Villagrande del Soto"}


def test_villagrande_soto_sin_articulo_resuelve_sola() -> None:
    # "del" se quita al normalizar: no hace falta escribirlo para que el
    # nombre completo deje de ser ambiguo.
    h = _horarios()
    m = matcher.Matcher(h)
    for texto in ("villagrande soto", "Villagrande del Soto"):
        r = m.buscar(texto)
        assert r.tipo == "unico"
        assert _nombres(h, r) == ["Villagrande del Soto"]


def test_villagrande_de_riomayor_y_del_soto_resuelven_solos() -> None:
    h = _horarios()
    m = matcher.Matcher(h)
    r = m.buscar("villagrande de riomayor")
    assert r.tipo == "unico"
    assert _nombres(h, r) == ["Villagrande de Riomayor"]
    r = m.buscar("villagrande del soto")
    assert r.tipo == "unico"
    assert _nombres(h, r) == ["Villagrande del Soto"]


def test_villagrande_siempre_pregunta() -> None:
    h = _horarios()
    m = matcher.Matcher(h)

    esperadas = {"Villagrande de Riomayor", "Villagrande del Soto"}

    r = m.buscar("villagrande")
    assert r.tipo == "elegir"
    assert set(_nombres(h, r)) == esperadas

    r = m.buscar("villagrand")  # incompleto, pero sigue siendo prefijo de las dos
    assert r.tipo == "elegir"  # nunca 'confirmar', aunque sea una errata
    assert set(_nombres(h, r)) == esperadas

    r = m.buscar("Villagrande de Riomayor")
    assert r.tipo == "unico"
    assert _nombres(h, r) == ["Villagrande de Riomayor"]


def test_carrascal_montealto_fuenteclara_odalla_unicos() -> None:
    h = _horarios()
    m = matcher.Matcher(h)
    for nombre in ("Carrascal", "Montealto", "Fuenteclara", "Odalla", "Peñablanca"):
        r = m.buscar(nombre)
        assert r.tipo == "unico", nombre
        assert _nombres(h, r) == [nombre], nombre


def test_errata_unica_confirma() -> None:
    h = _horarios()
    m = matcher.Matcher(h)

    r = m.buscar("pozolengo")
    assert r.tipo == "confirmar"
    assert _nombres(h, r) == ["Pozoluengo"]

    r = m.buscar("zarge")
    assert r.tipo == "confirmar"
    assert _nombres(h, r) == ["Zarfe"]


def test_errata_distancia_2_en_clave_corta_no_coincide() -> None:
    # 'zarfe' tiene 5 letras (umbral <=1); una query a distancia 2 no debe
    # generar ninguna candidata.
    assert matcher.damerau("zorfa", "zarfe") == 2
    h = _horarios()
    m = matcher.Matcher(h)
    r = m.buscar("zorfa")
    assert r.tipo == "sin_coincidencia"


def test_menos_de_minimo_letras_sin_exacto() -> None:
    h = _horarios()
    m = matcher.Matcher(h)
    for texto in ("po", "z"):
        r = m.buscar(texto)
        assert r.tipo == "sin_coincidencia"


def test_relleno_inicial_se_quita() -> None:
    h = _horarios()
    m = matcher.Matcher(h)

    r = m.buscar("desde pozoluengo")
    assert r.tipo == "unico"
    assert _nombres(h, r) == ["Pozoluengo"]

    r = m.buscar("a la vereda")
    assert r.tipo == "unico"
    assert _nombres(h, r) == ["La Vereda"]

    r = m.buscar("voy a riomayor")
    assert r.tipo == "unico"
    assert _nombres(h, r) == ["Riomayor"]


def test_relleno_inicial_con_puntuacion() -> None:
    h = _horarios()
    m = matcher.Matcher(h)
    for texto in ("¿desde pozoluengo?", "Desde, Pozoluengo", "¿Hacia Pozoluengo?"):
        r = m.buscar(texto)
        assert r.tipo == "unico", texto
        assert _nombres(h, r) == ["Pozoluengo"]


def test_mayusculas_tildes_y_espacios() -> None:
    h = _horarios()
    m = matcher.Matcher(h)
    for texto, esperado in (
        ("POZOLUENGO", "Pozoluengo"),
        ("  pOzOlUeNgO  ", "Pozoluengo"),
        ("RIOMAYOR", "Riomayor"),
        ("riomayor", "Riomayor"),
        ("PENABLANCA", "Peñablanca"),
        ("peñablanca", "Peñablanca"),
    ):
        r = m.buscar(texto)
        assert r.tipo == "unico", texto
        assert _nombres(h, r) == [esperado], texto


def test_nombre_de_parada_exacto() -> None:
    h = _horarios()
    m = matcher.Matcher(h)
    r = m.buscar("Pozoluengo (Hospital)")
    assert r.tipo == "unico"
    assert _nombres(h, r) == ["Pozoluengo"]


def test_nombre_de_parada_con_coma() -> None:
    h = _horarios()
    m = matcher.Matcher(h)
    r = m.buscar("Odalla (cruce, gasolinera)")
    assert r.tipo == "unico"
    assert _nombres(h, r) == ["Odalla"]


def test_alias_el_cruce() -> None:
    h = _horarios()
    m = matcher.Matcher(h)
    r = m.buscar("el cruce")
    assert r.tipo == "unico"
    assert _nombres(h, r) == ["Cruce del Risco"]


def test_sin_coincidencia() -> None:
    h = _horarios()
    m = matcher.Matcher(h)
    for texto in ("pozoluengo riomayor", "xyz", "la", ""):
        r = m.buscar(texto)
        assert r.tipo == "sin_coincidencia"


def test_parada_homonima_en_dos_localidades_pregunta() -> None:
    # "Cruce Sur" es el nombre exacto de una parada en Corralejo y otra en
    # Fontanar: no debe resolver en silencio a una de las dos.
    h = _horarios()
    m = matcher.Matcher(h)
    r = m.buscar("Cruce Sur")
    assert r.tipo == "elegir"
    assert set(_nombres(h, r)) == {"Corralejo", "Fontanar"}


def test_errata_descarta_por_longitud_antes_de_calcular_damerau(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    h = _horarios()
    m = matcher.Matcher(h)
    llamadas = []
    original = matcher.damerau

    def contado(a: str, b: str) -> int:
        llamadas.append((a, b))
        return original(a, b)

    monkeypatch.setattr(matcher, "damerau", contado)
    m.buscar("zorfa")  # 5 letras, muy lejos de nombres largos como "villagrande..."
    assert all(abs(len(a) - len(b)) <= 2 for a, b in llamadas)


def test_sin_alias_no_reconocido() -> None:
    # 'soto' es la segunda palabra de "Villagrande del Soto" pero no tiene
    # alias propio: no debe reconocerse sola.
    h = _horarios()
    m = matcher.Matcher(h)
    r = m.buscar("soto")
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


# ── lineas() sobre horarios_ficticios/ ──────────────────────────────────────


def test_zonas_ya_no_existe() -> None:
    assert not hasattr(matcher, "zonas")


def test_lineas_en_orden_de_titulo_con_pueblos_ordenados() -> None:
    h = _horarios()
    ls = matcher.lineas(h)
    assert len(ls) == 8
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


def test_lineas_pendientes_no_aparecen_en_ninguna_linea() -> None:
    h = loader.cargar(FIXTURES / "horarios_pendientes")
    ids = {loc.id for _, locs in matcher.lineas(h) for loc in locs}
    assert "aldea-a" not in ids
    assert "aldea-b" not in ids
    assert {"pueblo-a", "pueblo-b", "pueblo-c"} <= ids


# ── propiedad: cada localidad real, escrita con su nombre exacto ───────────


def test_propiedad_toda_localidad_por_su_nombre_exacto() -> None:
    # El nombre oficial completo de cada localidad es único incluso para el
    # par Villagrande (de Riomayor / del Soto): la ambigüedad declarada solo
    # salta al escribir el prefijo compartido "villagrande" (ver
    # test_villagrande_siempre_pregunta), nunca al escribir el nombre
    # completo.
    h = _horarios()
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
