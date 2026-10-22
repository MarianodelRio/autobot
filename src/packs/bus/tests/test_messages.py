"""packs/bus/tests/test_messages.py — cabecera de fecha y mensaje de "sin servicio" del
resultado (buscaBus/design.md, 4.6), con los horarios reales de `horarios/`."""

from __future__ import annotations

from datetime import date

from packs.bus import loader, query
from packs.bus.messages import msg_resultado
from packs.bus.tests.compat import CONFIG, HORARIOS_REAL

HORARIOS = loader.cargar(HORARIOS_REAL)


def _mensaje(origen: str, destino: str, fecha: date) -> str:
    c = query.consultar(HORARIOS, origen, destino, fecha)
    nombres = HORARIOS.modelo.localidades
    return msg_resultado(
        CONFIG, c, HORARIOS, nombres[origen].nombre, nombres[destino].nombre, fecha
    )


def test_invierno_muestra_horario_de_invierno() -> None:
    # miércoles 02/12/2026
    assert "horario de invierno" in _mensaje("pozoblanco", "cordoba", date(2026, 12, 2))


def test_temporada_sin_nombre_publico_no_muestra_horario_de() -> None:
    texto = _mensaje("ochavillos", "cordoba", date(2026, 12, 2))
    assert "horario de" not in texto
    assert "📅 Miércoles 02/12" in texto


def test_agosto_con_varias_temporadas_no_muestra_horario_de() -> None:
    # domingo 08/08/2027: agosto + anual en las líneas implicadas
    texto = _mensaje("cordoba", "penarroya-pueblonuevo", date(2027, 8, 8))
    assert "horario de" not in texto
    assert " / " not in texto


def test_badajoz_agosto_muestra_horario_de_agosto() -> None:
    texto = _mensaje("cordoba", "badajoz", date(2026, 8, 7))
    assert "horario de agosto" in texto


def test_festivo_en_agosto_gana_a_la_temporada() -> None:
    texto = _mensaje("cordoba", "badajoz", date(2026, 8, 15))
    assert "festivo (Asunción)" in texto
    assert "horario de" not in texto


def test_siguiente_dia_a_mas_de_7_dias_aclara_el_trayecto() -> None:
    # viernes 07/08/2026: Córdoba -> Badajoz retoma el viernes 04/09
    texto = _mensaje("cordoba", "badajoz", date(2026, 8, 7))
    assert (
        "Ese día no hay servicio en este trayecto. El siguiente día con salidas es viernes 04/09."
    ) in texto


def test_siguiente_dia_cercano_mantiene_el_texto_corto() -> None:
    texto = _mensaje("ochavillos", "cordoba", date(2026, 10, 3))
    assert "Ese día no hay servicio. El siguiente día con salidas es lunes 05/10." in texto
    assert "en este trayecto" not in texto


def test_ningun_mensaje_filtra_nombres_internos_de_temporada() -> None:
    fechas = [date(2026, 12, 2), date(2027, 2, 3), date(2027, 8, 8), date(2026, 8, 7)]
    pares = [
        ("pozoblanco", "cordoba"),
        ("cordoba", "badajoz"),
        ("ochavillos", "cordoba"),
        ("cordoba", "penarroya-pueblonuevo"),
    ]
    for fecha in fechas:
        for o, d in pares:
            texto = _mensaje(o, d, fecha)
            assert "anual" not in texto.lower(), (o, d, fecha)
            assert "septiembre-julio" not in texto, (o, d, fecha)
            assert " / " not in texto, (o, d, fecha)
            assert len(texto) <= 4096
