"""packs/bus/tests/test_fechas.py — lector de fechas en formato cerrado (buscaBus/design.md 4.5)."""

from __future__ import annotations

from datetime import date

from packs.bus import fechas

HOY = date(2026, 9, 27)


def test_variaciones_de_separador() -> None:
    esperado = date(2026, 12, 25)
    for texto in ("25/12", "25-12", "25.12", "25 12", " 25 / 12 "):
        r = fechas.leer_fecha(texto, HOY)
        assert r.estado == "ok", texto
        assert r.fecha == esperado, texto


def test_dia_mes_de_un_digito() -> None:
    for texto in ("5/1", "05/01"):
        r = fechas.leer_fecha(texto, HOY)
        assert r.estado == "ok"
        assert r.fecha == date(2027, 1, 5)


def test_hoy_es_ok() -> None:
    r = fechas.leer_fecha("27/09", HOY)
    assert r.estado == "ok"
    assert r.fecha == HOY


def test_fechas_recientes_pasadas() -> None:
    for texto in ("20/09", "26/09"):
        r = fechas.leer_fecha(texto, HOY)
        assert r.estado == "pasada", texto


def test_limite_30_dias_exacto_es_pasada() -> None:
    r = fechas.leer_fecha("28/08", HOY)
    assert r.estado == "pasada"


def test_31_dias_es_ok_proximo_anio() -> None:
    r = fechas.leer_fecha("27/08", HOY)
    assert r.estado == "ok"
    assert r.fecha == date(2027, 8, 27)


def test_pasada_con_hoy_en_enero() -> None:
    hoy = date(2027, 1, 5)
    r = fechas.leer_fecha("28/12", hoy)
    assert r.estado == "pasada"


def test_con_anio_explicito() -> None:
    for texto in ("25/12/2026", "25/12/26"):
        r = fechas.leer_fecha(texto, HOY)
        assert r.estado == "ok"
        assert r.fecha == date(2026, 12, 25)


def test_con_anio_explicito_pasada() -> None:
    r = fechas.leer_fecha("01/09/2026", HOY)
    assert r.estado == "pasada"


def test_fechas_inexistentes() -> None:
    for texto in ("31/02", "12/25", "0/5", "32/1"):
        r = fechas.leer_fecha(texto, HOY)
        assert r.estado == "inexistente", texto


def test_29_febrero_con_anio_no_bisiesto_es_inexistente() -> None:
    r = fechas.leer_fecha("29/02/2027", HOY)
    assert r.estado == "inexistente"


def test_29_febrero_sin_anio_busca_proximo_bisiesto() -> None:
    r = fechas.leer_fecha("29/02", HOY)
    assert r.estado == "ok"
    assert r.fecha == date(2028, 2, 29)


def test_lenguaje_natural_y_formatos_no_admitidos() -> None:
    textos = (
        "mañana",
        "el viernes",
        "25 de diciembre",
        "por la mañana",
        "25/12/202",
        "25/12/2026 10:00",
        "",
    )
    for texto in textos:
        r = fechas.leer_fecha(texto, HOY)
        assert r.estado == "formato", texto
