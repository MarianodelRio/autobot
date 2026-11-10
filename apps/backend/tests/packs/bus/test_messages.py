"""packs/bus/tests/test_messages.py — cabecera de fecha y mensaje de "sin servicio" del
resultado, con los horarios ficticios de `horarios_ficticios/`."""

from __future__ import annotations

import dataclasses
from datetime import date

from packs.bus import loader, query
from packs.bus.messages import msg_resultado
from packs.bus.modelo import Temporada
from tests.packs.bus.conversation_harness import CONFIG, HORARIOS_FICTICIOS

HORARIOS = loader.cargar(HORARIOS_FICTICIOS)


def _mensaje(
    origen: str,
    destino: str,
    fecha: date,
    temporadas: tuple[tuple[str, Temporada], ...] | None = None,
) -> str:
    c = query.consultar(HORARIOS, origen, destino, fecha)
    if temporadas is not None:
        c = dataclasses.replace(c, temporadas=temporadas)
    nombres = HORARIOS.modelo.localidades
    return msg_resultado(
        CONFIG, c, HORARIOS, nombres[origen].nombre, nombres[destino].nombre, fecha
    )


def test_invierno_muestra_horario_de_invierno() -> None:
    # miércoles 02/12/2026
    assert "horario de invierno" in _mensaje("riomayor", "montealto", date(2026, 12, 2))


def test_temporada_sin_nombre_publico_no_muestra_horario_de() -> None:
    # riomayor-ribazo usa la temporada "anual", sin nombre público.
    texto = _mensaje("riomayor", "ribazo", date(2026, 10, 5))
    assert "horario de" not in texto
    assert "📅 Lunes 05/10" in texto


def test_varias_temporadas_distintas_no_muestra_horario_de() -> None:
    # Dos temporadas con nombres distintos en el mismo resultado (forzado):
    # nunca se muestra "horario de X" ni se unen con " / ".
    c = query.consultar(HORARIOS, "riomayor", "montealto", date(2026, 12, 2))
    (linea, _temporada), *resto = c.temporadas
    ambiguo = ((linea, Temporada(nombre="verano", rango="x")), *c.temporadas)
    texto = _mensaje("riomayor", "montealto", date(2026, 12, 2), temporadas=ambiguo)
    assert "horario de" not in texto
    assert " / " not in texto


def test_agosto_muestra_horario_de_agosto() -> None:
    texto = _mensaje("riomayor", "montealto", date(2027, 8, 4))
    assert "horario de agosto" in texto


def test_festivo_en_agosto_gana_a_la_temporada() -> None:
    texto = _mensaje("riomayor", "montealto", date(2026, 8, 15))
    assert "festivo (Asunción)" in texto
    assert "horario de" not in texto


def test_siguiente_dia_a_mas_de_7_dias_aclara_el_trayecto() -> None:
    # sábado 01/08/2026: Riomayor -> Montealto no circula en agosto y
    # retoma el martes 01/09.
    texto = _mensaje("riomayor", "montealto", date(2026, 8, 1))
    assert (
        "Ese día no hay servicio en este trayecto. El siguiente día con salidas es martes 01/09."
    ) in texto


def test_siguiente_dia_cercano_mantiene_el_texto_corto() -> None:
    texto = _mensaje("riomayor", "ribazo", date(2026, 10, 3))
    assert "Ese día no hay servicio. El siguiente día con salidas es lunes 05/10." in texto
    assert "en este trayecto" not in texto


def test_ningun_mensaje_filtra_nombres_internos_de_temporada() -> None:
    fechas = [date(2026, 12, 2), date(2027, 2, 3), date(2027, 8, 8), date(2026, 8, 7)]
    pares = [
        ("pozoluengo", "riomayor"),
        ("riomayor", "ribazo"),
        ("riomayor", "montealto"),
        ("riomayor", "fuenteclara"),
    ]
    for fecha in fechas:
        for o, d in pares:
            texto = _mensaje(o, d, fecha)
            assert "anual" not in texto.lower(), (o, d, fecha)
            assert "septiembre-julio" not in texto, (o, d, fecha)
            assert " / " not in texto, (o, d, fecha)
            assert len(texto) <= 4096
