"""packs/bus/tests/test_query.py — motor de consulta.

Pruebas doradas contra `horarios/` real (verificadas a mano contra
horarios/lineas/*.yaml) más pruebas sobre la mezcla sintética
tests/fixtures/horarios_motor/ para los casos especiales (a demanda, viernes
lectivo, no_circula, sin_datos, fusión)."""

from __future__ import annotations

from datetime import date, datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from packs.bus import loader, query
from packs.bus.calendario import InfoDia

FIXTURES = Path(__file__).parent / "fixtures"
HORARIOS_REAL = FIXTURES / "horarios_real"

HORARIOS = loader.cargar(HORARIOS_REAL)
MOTOR = loader.cargar(FIXTURES / "horarios_motor")

MADRID = ZoneInfo("Europe/Madrid")


def _info(consulta: query.Consulta) -> InfoDia:
    assert consulta.info_dia is not None
    return consulta.info_dia


def _horas(consulta: query.Consulta) -> list[tuple[str, str]]:
    return [
        (s.hora_salida.strftime("%H:%M"), s.hora_llegada.strftime("%H:%M"))
        for s in consulta.salidas
    ]


# ── Doradas: Pozoblanco <-> Córdoba ──────────────────────────────────────────


def test_pozoblanco_cordoba_miercoles_laborable() -> None:
    c = query.consultar(HORARIOS, "pozoblanco", "cordoba", date(2026, 9, 30))
    assert c.estado == "con_salidas"
    assert _horas(c) == [
        ("06:55", "08:15"),
        ("08:15", "09:30"),
        ("10:00", "11:25"),
        ("15:15", "16:30"),
        ("18:00", "19:15"),
    ]
    assert all(s.parada_origen == "POZ" and s.parada_destino == "COR" for s in c.salidas)


def test_pozoblanco_cordoba_festivo_lunes() -> None:
    c = query.consultar(HORARIOS, "pozoblanco", "cordoba", date(2026, 10, 12))
    assert c.estado == "con_salidas"
    assert _info(c).es_festivo is True
    assert _horas(c) == [("08:15", "09:30"), ("15:15", "16:30"), ("17:45", "19:00")]


def test_pozoblanco_cordoba_festivo_en_sabado() -> None:
    c = query.consultar(HORARIOS, "pozoblanco", "cordoba", date(2027, 5, 1))
    assert c.estado == "con_salidas"
    assert _info(c).es_festivo is True
    # mismas 3 salidas que el festivo anterior, no el conjunto de sábado.
    assert _horas(c) == [("08:15", "09:30"), ("15:15", "16:30"), ("17:45", "19:00")]


def test_pozoblanco_cordoba_ya_salio() -> None:
    ahora = datetime(2026, 9, 30, 10, 30, tzinfo=MADRID)
    c = query.consultar(HORARIOS, "pozoblanco", "cordoba", date(2026, 9, 30), ahora=ahora)
    ya_salio = [s.ya_salio for s in c.salidas]
    assert ya_salio == [True, True, True, False, False]


def test_cordoba_villaharta_a_demanda() -> None:
    c = query.consultar(HORARIOS, "cordoba", "villaharta", date(2026, 9, 30))
    assert _horas(c) == [("13:10", "13:45"), ("18:30", "19:05"), ("20:00", "20:35")]
    for s in c.salidas:
        assert any("957 42 90 30" in n for n in s.notas)


def test_villaharta_cordoba_invierno_laborable() -> None:
    c = query.consultar(HORARIOS, "villaharta", "cordoba", date(2026, 9, 30))
    assert _horas(c) == [
        ("08:50", "09:30"),
        ("10:35", "11:25"),
        ("15:50", "16:30"),
        ("18:35", "19:15"),
    ]
    a_demanda = [any("957 42 90 30" in n for n in s.notas) for s in c.salidas]
    # 10:35 no es a demanda; 08:50, 15:50 y 18:35 sí.
    assert a_demanda == [True, False, True, True]


def test_cordoba_villanueva_de_cordoba_solo_una_con_viajeros_desde_cordoba() -> None:
    c = query.consultar(HORARIOS, "cordoba", "villanueva-de-cordoba", date(2026, 9, 30))
    assert _horas(c) == [
        ("12:00", "13:35"),
        ("13:10", "15:10"),
        ("18:30", "20:10"),
        ("20:00", "21:45"),
    ]
    con_nota = [s for s in c.salidas if any("viajeros" in n for n in s.notas)]
    assert len(con_nota) == 1
    assert con_nota[0].hora_salida == time(20, 0)
    assert any("viajeros" in n for n in con_nota[0].notas)


def test_ochavillos_cordoba_sabado_sin_servicio() -> None:
    c = query.consultar(HORARIOS, "ochavillos", "cordoba", date(2026, 10, 3))
    assert c.estado == "sin_servicio"
    assert c.siguiente_con_servicio == date(2026, 10, 5)


def test_ochavillos_cordoba_festivo_lunes_sin_servicio() -> None:
    c = query.consultar(HORARIOS, "ochavillos", "cordoba", date(2026, 10, 12))
    assert c.estado == "sin_servicio"
    assert c.siguiente_con_servicio == date(2026, 10, 13)


def test_ochavillos_pozoblanco_sin_trayecto() -> None:
    c = query.consultar(HORARIOS, "ochavillos", "pozoblanco", date(2026, 9, 30))
    assert c.estado == "sin_trayecto"
    assert c.siguiente_con_servicio is None


def test_pozoblanco_cordoba_fuera_de_calendario() -> None:
    c = query.consultar(HORARIOS, "pozoblanco", "cordoba", date(2028, 1, 2))
    assert c.estado == "sin_datos"
    assert c.fuera_de_calendario is True
    assert c.salidas == ()


def test_pozoblanco_cordoba_fuera_de_calendario_2027_10_01() -> None:
    # El curso 2027-28 no está cargado: vigencia termina el 31/08/2027.
    c = query.consultar(HORARIOS, "pozoblanco", "cordoba", date(2027, 10, 1))
    assert c.estado == "sin_datos"
    assert c.fuera_de_calendario is True


def test_origen_igual_destino_lanza_valueerror() -> None:
    with pytest.raises(ValueError):
        query.consultar(HORARIOS, "cordoba", "cordoba", date(2026, 9, 30))


def test_localidad_desconocida_lanza_valueerror() -> None:
    with pytest.raises(ValueError):
        query.consultar(HORARIOS, "cordoba", "no-existe", date(2026, 9, 30))


def test_destinos_desde_ochavillos() -> None:
    destinos = query.destinos_desde(HORARIOS, "ochavillos")
    assert destinos == frozenset(
        {"la-herreria", "fuente-palmera", "la-ventilla", "fuencubierta", "cordoba"}
    )
    assert "ochavillos" not in destinos


# ── Sintéticas: tests/fixtures/horarios_motor/ ───────────────────────────────


def test_viernes_lectivo_parada_no_lectivo_falla_pero_intermedia_sin_condicion_pasa() -> None:
    # 28/08/2026 es viernes pero anterior a inicio_clases: no es lectivo.
    fecha = date(2026, 8, 28)
    c_b = query.consultar(MOTOR, "pueblo-a", "pueblo-b", fecha)
    assert c_b.estado == "con_salidas"
    assert any(s.hora_salida == time(8, 0) for s in c_b.salidas)

    c_c = query.consultar(MOTOR, "pueblo-a", "pueblo-c", fecha)
    # la salida de las 08:00 (condición V solo en C) no debe aparecer; la de
    # las 09:00 (condición de viaje) tampoco.
    assert c_c.estado == "sin_servicio"


def test_viernes_lectivo_si_es_lectivo_aparecen_ambas() -> None:
    # 04/09/2026 es viernes, dentro de curso: es lectivo.
    fecha = date(2026, 9, 4)
    c_c = query.consultar(MOTOR, "pueblo-a", "pueblo-c", fecha)
    assert c_c.estado == "con_salidas"
    assert _horas(c_c) == [("08:00", "08:20"), ("09:00", "09:20")]
    salida_v = next(s for s in c_c.salidas if s.hora_salida == time(8, 0))
    assert any("viernes" in n.lower() for n in salida_v.notas)


def test_no_circula_en_agosto() -> None:
    c_agosto = query.consultar(MOTOR, "pueblo-n", "pueblo-o", date(2026, 8, 5))
    assert c_agosto.estado == "sin_servicio"

    c_septiembre = query.consultar(MOTOR, "pueblo-n", "pueblo-o", date(2026, 9, 2))
    assert c_septiembre.estado == "con_salidas"


def test_sin_servicio_sin_ningun_dia_con_salidas_en_45_dias_da_none() -> None:
    # linea-sin-servicio-largo no circula en agosto ni septiembre (61 días):
    # desde el 01/08/2026 los 45 días siguientes no tienen salidas.
    assert query.SIGUIENTE_CON_SERVICIO_DIAS == 45
    c = query.consultar(MOTOR, "pueblo-p", "pueblo-q", date(2026, 8, 1))
    assert c.estado == "sin_servicio"
    assert c.siguiente_con_servicio is None


def test_siguiente_con_servicio_a_mas_de_7_dias() -> None:
    # 28/08/2026 -> la línea retoma el 01/10/2026 (34 días después).
    c = query.consultar(MOTOR, "pueblo-p", "pueblo-q", date(2026, 8, 28))
    assert c.estado == "sin_servicio"
    assert c.siguiente_con_servicio == date(2026, 10, 1)


def test_siguiente_con_servicio_en_el_dia_45_exacto() -> None:
    # 16/08/2026 + 45 = 30/09... aún no circula; 17/08 + 45 = 01/10: sí.
    c = query.consultar(MOTOR, "pueblo-p", "pueblo-q", date(2026, 8, 17))
    assert c.siguiente_con_servicio == date(2026, 10, 1)
    c = query.consultar(MOTOR, "pueblo-p", "pueblo-q", date(2026, 8, 16))
    assert c.siguiente_con_servicio is None


def test_ventana_de_siguiente_con_servicio_configurable() -> None:
    # `next_day_search_days`: con 46 días el 16/08 llega al 01/10;
    # con 33, el 28/08 ya no llega (está a 34 días).
    c = query.consultar(MOTOR, "pueblo-p", "pueblo-q", date(2026, 8, 16), dias_siguiente=46)
    assert c.siguiente_con_servicio == date(2026, 10, 1)
    c = query.consultar(MOTOR, "pueblo-p", "pueblo-q", date(2026, 8, 28), dias_siguiente=33)
    assert c.siguiente_con_servicio is None
    c = query.consultar(MOTOR, "pueblo-p", "pueblo-q", date(2026, 8, 28), dias_siguiente=34)
    assert c.siguiente_con_servicio == date(2026, 10, 1)


def test_dia_sin_datos_dentro_de_la_ventana_no_cuenta_como_con_salidas() -> None:
    c = query.consultar(MOTOR, "pueblo-g", "pueblo-h", date(2026, 9, 2))
    assert c.estado == "sin_datos"
    # el siguiente día es el primero con salidas reales, no uno sin datos
    sig = c.siguiente_con_servicio
    assert sig is not None
    assert query.consultar(MOTOR, "pueblo-g", "pueblo-h", sig).estado == "con_salidas"
    intermedio = date(2026, 9, 3)
    assert intermedio < sig
    c_int = query.consultar(MOTOR, "pueblo-g", "pueblo-h", intermedio)
    assert c_int.estado == "sin_datos"


def test_sin_datos_combinado_con_horario_muestra_salidas_y_aviso() -> None:
    c = query.consultar(MOTOR, "pueblo-e", "pueblo-f", date(2026, 9, 2))
    assert c.estado == "con_salidas"
    assert _horas(c) == [("09:00", "09:15")]
    assert "linea-sin-datos" in c.lineas_sin_datos


def test_sin_datos_solo_es_sin_datos_nunca_sin_servicio() -> None:
    c = query.consultar(MOTOR, "pueblo-g", "pueblo-h", date(2026, 9, 2))
    assert c.estado == "sin_datos"
    assert c.salidas == ()


def test_fusion_de_lineas_con_mismo_autobus() -> None:
    c = query.consultar(MOTOR, "pueblo-i", "pueblo-j", date(2026, 9, 2))
    assert len(c.salidas) == 1
    salida = c.salidas[0]
    assert set(salida.lineas) == {"linea-fusion-1", "linea-fusion-2"}
    assert "Aviso uno." in salida.notas
    assert "Aviso dos." in salida.notas


def test_a_demanda_en_origen_lleva_nota() -> None:
    c = query.consultar(MOTOR, "pueblo-k", "pueblo-l", date(2026, 9, 2))
    salida_demanda = next(s for s in c.salidas if s.hora_salida == time(10, 0))
    assert any("957 00 00 00" in n for n in salida_demanda.notas)


def test_a_demanda_en_parada_intermedia_no_lleva_nota() -> None:
    c = query.consultar(MOTOR, "pueblo-k", "pueblo-l", date(2026, 9, 2))
    salida_normal = next(s for s in c.salidas if s.hora_salida == time(11, 0))
    assert salida_normal.notas == ()


def test_siguiente_con_servicio_nunca_pasa_de_vigencia_fin() -> None:
    # linea-agosto (pueblo-n <-> pueblo-o) no circula en agosto de ningún año
    # y retoma el 1 de septiembre. En 2027 ese 1 de septiembre cae fuera de
    # la vigencia del calendario (que termina el 31/08/2027, ver
    # tests/fixtures/horarios_motor/calendario.yaml): aunque el servicio
    # "existiría" ese día si se mirase solo el horario de la línea,
    # siguiente_con_servicio debe ser None en vez de devolver una fecha sin
    # calendario cargado.
    c = query.consultar(MOTOR, "pueblo-n", "pueblo-o", date(2027, 8, 25))
    assert c.estado == "sin_servicio"
    assert c.siguiente_con_servicio is None


# ── Días sin servicio en ninguna línea (P03g) ───────────────────────────────


def _pares_con_trayecto(horarios: loader.Horarios) -> list[tuple[str, str]]:
    return [
        (o, d)
        for o in horarios.modelo.localidades
        for d in sorted(query.destinos_desde(horarios, o))
    ]


@pytest.mark.parametrize("fecha", [date(2026, 12, 25), date(2027, 1, 1)])
def test_sin_servicio_general_en_todos_los_pares_de_las_lineas(fecha: date) -> None:
    pares = _pares_con_trayecto(HORARIOS)
    assert pares
    for origen, destino in pares:
        c = query.consultar(HORARIOS, origen, destino, fecha)
        assert c.estado == "sin_servicio", (origen, destino)
        assert c.sin_servicio_general is True
        assert c.salidas == ()
        assert c.lineas_sin_datos == ()


def test_sin_servicio_general_cabecera_conserva_nombre_del_festivo() -> None:
    c = query.consultar(HORARIOS, "pozoblanco", "cordoba", date(2027, 1, 1))
    assert _info(c).nombre_festivo == "Año Nuevo"
    assert c.siguiente_con_servicio == date(2027, 1, 2)


def test_sin_servicio_general_siguiente_es_el_primer_dia_con_salidas() -> None:
    c = query.consultar(HORARIOS, "pozoblanco", "cordoba", date(2026, 12, 25))
    assert c.siguiente_con_servicio == date(2026, 12, 26)
    real = query.consultar(HORARIOS, "pozoblanco", "cordoba", date(2026, 12, 26))
    assert real.estado == "con_salidas"


def test_siguiente_con_servicio_desde_24_12_salta_el_25_12() -> None:
    # Córdoba -> Badajoz no tiene salidas el 24, 25 ni 26/12/2026; el
    # siguiente día con salidas es el domingo 27 (el 25 se salta).
    c = query.consultar(HORARIOS, "cordoba", "badajoz", date(2026, 12, 24))
    assert c.estado == "sin_servicio"
    assert c.sin_servicio_general is False
    assert c.siguiente_con_servicio == date(2026, 12, 27)


def test_sin_servicio_general_no_pisa_sin_trayecto() -> None:
    c = query.consultar(HORARIOS, "ochavillos", "pozoblanco", date(2026, 12, 25))
    assert c.estado == "sin_trayecto"
    assert c.sin_servicio_general is False


def test_sin_servicio_general_tiene_prioridad_sobre_la_vigencia() -> None:
    c = query.consultar(HORARIOS, "pozoblanco", "cordoba", date(2027, 12, 25))
    assert c.estado == "sin_servicio"
    assert c.sin_servicio_general is True
    assert c.fuera_de_calendario is False
    # sin calendario más allá de 31/08/2027 no se puede calcular el siguiente.
    assert c.siguiente_con_servicio is None
    assert c.info_dia is not None and _info(c).nombre_festivo is None


def test_dia_fuera_de_vigencia_que_no_es_general_sigue_siendo_sin_datos() -> None:
    c = query.consultar(HORARIOS, "pozoblanco", "cordoba", date(2027, 12, 24))
    assert c.estado == "sin_datos"
    assert c.fuera_de_calendario is True


# ── Festivos locales por línea (P03e) ───────────────────────────────────────

FESTIVO_LOCAL = loader.cargar(FIXTURES / "horarios_festivo_local")


def test_festivo_local_de_cordoba_usa_las_salidas_de_festivos() -> None:
    # 08/09/2026 (martes, verano, Virgen de la Fuensanta) = mismas salidas
    # que un festivo general de verano (15/08/2026), no las del martes.
    local = query.consultar(HORARIOS, "pozoblanco", "cordoba", date(2026, 9, 8))
    general = query.consultar(HORARIOS, "pozoblanco", "cordoba", date(2026, 8, 15))
    laborable = query.consultar(HORARIOS, "pozoblanco", "cordoba", date(2026, 9, 9))
    assert local.estado == "con_salidas"
    assert (
        _horas(local)
        == _horas(general)
        == [("08:15", "09:30"), ("15:15", "16:30"), ("17:45", "19:00")]
    )
    assert _horas(local) != _horas(laborable)
    assert local.festivo_local == ("Virgen de la Fuensanta", "cordoba")
    assert _info(local).es_festivo is False  # InfoDia no cambia (P04)


def test_festivo_local_en_sabado_usa_festivos_no_sabado() -> None:
    # 24/10/2026 (sábado, San Rafael): 3 salidas como en domingo/festivo; un
    # sábado normal (17/10) tiene 2.
    local = query.consultar(HORARIOS, "pozoblanco", "cordoba", date(2026, 10, 24))
    sabado = query.consultar(HORARIOS, "pozoblanco", "cordoba", date(2026, 10, 17))
    assert _horas(local) == [("08:15", "09:30"), ("15:15", "16:30"), ("17:45", "19:00")]
    assert len(sabado.salidas) == 2
    assert sabado.festivo_local is None


def test_festivo_general_sin_festivo_local_no_rellena_festivo_local() -> None:
    # El validador impide que una fecha sea a la vez festivo general y local
    # (el caso combinado se prueba en test_calendario con clase_dia_linea).
    c = query.consultar(FESTIVO_LOCAL, "pueblo-b", "pueblo-c", date(2026, 12, 25))
    assert c.sin_servicio_general is False  # el fixture no declara 25/12
    assert _info(c).es_festivo is True
    assert c.festivo_local is None


def test_festivo_local_caso_mixto_cada_linea_con_su_clase() -> None:
    # 14/10/2026 (miércoles): linea-con-a (toca pueblo-a) usa festivos
    # (09:10), linea-sin-a usa miércoles (10:00). Una sola lista.
    c = query.consultar(FESTIVO_LOCAL, "pueblo-b", "pueblo-c", date(2026, 10, 14))
    assert c.estado == "con_salidas"
    assert _horas(c) == [("09:10", "09:20"), ("10:00", "10:10")]
    por_hora = {s.hora_salida.strftime("%H:%M"): s.lineas for s in c.salidas}
    assert por_hora["09:10"] == ("linea-con-a",)
    assert por_hora["10:00"] == ("linea-sin-a",)
    assert c.festivo_local == ("Fiesta local de A", "pueblo-a")
    # un miércoles sin festivo local: linea-con-a a su hora laborable
    normal = query.consultar(FESTIVO_LOCAL, "pueblo-b", "pueblo-c", date(2026, 10, 15))
    assert _horas(normal) == [("08:10", "08:20"), ("10:00", "10:10")]
    assert normal.festivo_local is None


def test_festivo_local_no_activa_solo_viernes_lectivo_en_clase_festivos() -> None:
    # 16/10/2026 es viernes lectivo y festivo local de A. La tabla de
    # festivos de linea-viernes-a lleva "solo viernes lectivo": no puede
    # activarse porque la línea está en la clase festivos.
    c = query.consultar(FESTIVO_LOCAL, "pueblo-d", "pueblo-e", date(2026, 10, 16))
    assert c.salidas == ()
    assert c.estado == "sin_servicio"
    assert c.festivo_local == ("Feria de A", "pueblo-a")
    # el viernes lectivo anterior sin festivo: sale la de lunes-viernes
    normal = query.consultar(FESTIVO_LOCAL, "pueblo-d", "pueblo-e", date(2026, 10, 9))
    assert _horas(normal) == [("06:10", "06:20")]


# ── Trayectos no vendibles (P12b) ───────────────────────────────────────────

_NO_VENDIBLES = ("cordoba", "campus-de-rabanales", "alcolea")


def test_no_vendible_las_seis_direcciones_sin_salidas() -> None:
    for origen in _NO_VENDIBLES:
        for destino in _NO_VENDIBLES:
            if origen == destino:
                continue
            assert query.es_no_vendible(HORARIOS, origen, destino)
            c = query.consultar(HORARIOS, origen, destino, date(2026, 9, 30))
            assert c.estado == "no_vendible", (origen, destino)
            assert c.salidas == ()
            assert c.siguiente_con_servicio is None


def test_no_vendible_tiene_prioridad_sobre_sin_servicio_general_y_vigencia() -> None:
    for fecha in (date(2026, 12, 25), date(2030, 6, 1)):
        c = query.consultar(HORARIOS, "cordoba", "alcolea", fecha)
        assert c.estado == "no_vendible"
        assert c.sin_servicio_general is False


def test_es_no_vendible_es_falso_para_pares_normales() -> None:
    assert not query.es_no_vendible(HORARIOS, "cordoba", "pozoblanco")
    assert not query.es_no_vendible(HORARIOS, "alcolea", "adamuz")


def test_destinos_desde_filtra_los_no_vendibles() -> None:
    assert "alcolea" not in query.destinos_desde(HORARIOS, "cordoba")
    assert "campus-de-rabanales" not in query.destinos_desde(HORARIOS, "cordoba")
    assert "alcolea" not in query.destinos_desde(HORARIOS, "campus-de-rabanales")
    assert "cordoba" not in query.destinos_desde(HORARIOS, "alcolea")
    # el resto de destinos de Alcolea no se toca
    assert "adamuz" in query.destinos_desde(HORARIOS, "alcolea")


# ── Fase 1b-1: Fuente Carreteros, Villaviciosa, Belalcázar-Pozoblanco y TORR ─


def _por_hora(c: query.Consulta) -> dict[str, query.Salida]:
    return {s.hora_salida.strftime("%H:%M"): s for s in c.salidas}


def test_villaviciosa_viernes_lectivo_incluye_las_16_00() -> None:
    c = query.consultar(HORARIOS, "cordoba", "villaviciosa-de-cordoba", date(2026, 10, 2))
    assert c.estado == "con_salidas"
    assert _horas(c) == [("13:10", "14:05"), ("16:00", "17:00"), ("18:30", "19:25")]


def test_villaviciosa_viernes_no_lectivo_jueves_y_lunes_sin_las_16_00() -> None:
    esperado = [("13:10", "14:05"), ("18:30", "19:25")]
    for fecha in (date(2027, 2, 26), date(2026, 10, 1), date(2026, 10, 5)):
        c = query.consultar(HORARIOS, "cordoba", "villaviciosa-de-cordoba", fecha)
        assert c.estado == "con_salidas", fecha
        assert _horas(c) == esperado, fecha


def test_cardena_pozoblanco_en_agosto_es_sin_servicio_no_sin_datos() -> None:
    c = query.consultar(HORARIOS, "cardena", "pozoblanco", date(2027, 8, 4))
    assert c.estado == "sin_servicio"
    assert c.salidas == ()
    assert c.lineas_sin_datos == ()
    c = query.consultar(HORARIOS, "cardena", "pozoblanco", date(2027, 7, 7))
    assert c.estado == "con_salidas"
    assert _horas(c) == [("09:00", "10:00")]


def test_pozoblanco_villanueva_cordoba_agosto_sin_la_linea_de_cardena() -> None:
    # pozoblanco-cordoba ya tiene salidas POZ -> VVC en verano (p.ej. 13:15
    # desde PZH, llegada 13:35): no se puede asertar la ausencia de esa
    # hora. Se asierta por línea: la de Cardeña no aparece y la de la
    # Estación AVE sí.
    c = query.consultar(HORARIOS, "pozoblanco", "villanueva-de-cordoba", date(2027, 8, 4))
    assert c.estado == "con_salidas"
    assert all("cardena-pozoblanco" not in s.lineas for s in c.salidas)
    por_hora = _por_hora(c)
    assert por_hora["15:55"].lineas == ("pozoblanco-estacion-ave",)
    assert por_hora["15:55"].parada_origen == "POZ"
    assert por_hora["15:55"].hora_llegada == time(16, 10)
    assert por_hora["13:15"].lineas == ("pozoblanco-cordoba",)


def test_torrecampo_pozoblanco_sabado_sin_servicio_y_siguiente_lunes() -> None:
    c = query.consultar(HORARIOS, "torrecampo", "pozoblanco", date(2026, 10, 3))
    assert c.estado == "sin_servicio"
    assert c.siguiente_con_servicio == date(2026, 10, 5)
    c = query.consultar(HORARIOS, "torrecampo", "pozoblanco", date(2026, 10, 5))
    assert c.estado == "con_salidas"
    assert [s.parada_destino for s in c.salidas] == ["PZH"]


def test_pozoblanco_estacion_ave_dia_laborable_de_invierno() -> None:
    c = query.consultar(HORARIOS, "pozoblanco", "estacion-ave-villanueva", date(2026, 10, 1))
    assert c.estado == "con_salidas"
    assert _horas(c) == [("15:55", "16:25"), ("17:45", "18:30")]
    assert all(s.parada_origen == "POZ" and s.parada_destino == "EAV" for s in c.salidas)


def test_festivo_local_de_cordoba_solo_afecta_a_las_lineas_que_tocan_cordoba() -> None:
    fecha = date(2026, 9, 8)
    for origen in ("fuente-carreteros", "villaviciosa-de-cordoba"):
        c = query.consultar(HORARIOS, origen, "cordoba", fecha)
        assert c.estado == "sin_servicio", origen
        assert c.festivo_local == ("Virgen de la Fuensanta", "cordoba"), origen
    c = query.consultar(HORARIOS, "torrecampo", "pozoblanco", fecha)
    assert c.estado == "con_salidas"
    assert _horas(c) == [("09:00", "09:20")]
    assert c.festivo_local is None
    c = query.consultar(HORARIOS, "belalcazar", "pozoblanco", fecha)
    assert c.estado == "con_salidas"
    assert _horas(c)[0] == ("09:20", "10:15")
    assert c.festivo_local is None


# ── Ciclo C1: llegada>salida y mismo autobús (fixture horarios_cicloC) ───────

CICLO_C = loader.cargar(FIXTURES / "horarios_cicloC")
MIERCOLES = date(2026, 9, 30)
NOTA_APROXIMADA = "Horarios de paso aproximados."


def test_cicloc_cordoba_penarroya_una_salida_con_las_dos_lineas() -> None:
    c = query.consultar(CICLO_C, "cordoba", "penarroya", MIERCOLES)
    assert c.estado == "con_salidas"
    primera = c.salidas[0]
    assert (
        primera.hora_salida.strftime("%H:%M"),
        primera.hora_llegada.strftime("%H:%M"),
    ) == ("10:30", "11:55")
    assert sorted(primera.lineas) == ["corta", "larga"]
    # el autobús compartido no sale duplicado
    assert sum(1 for s in c.salidas if s.hora_salida == time(10, 30)) == 1
    assert (primera.parada_origen, primera.parada_destino) == ("COR", "PNR")


def test_cicloc_penarroya_los_blazquez_sale_a_la_salida_de_penarroya() -> None:
    c = query.consultar(CICLO_C, "penarroya", "los-blazquez", MIERCOLES)
    assert _horas(c) == [("12:30", "13:20")]
    assert c.salidas[0].lineas == ("larga",)
    assert c.salidas[0].duracion_min == 50


def test_cicloc_cordoba_los_blazquez_una_sola_salida_de_punta_a_punta() -> None:
    c = query.consultar(CICLO_C, "cordoba", "los-blazquez", MIERCOLES)
    assert _horas(c) == [("10:30", "13:20")]
    assert c.salidas[0].duracion_min == 170


def test_cicloc_ya_salio_usa_la_salida_no_la_llegada() -> None:
    # A las 12:00 el autobús ya llegó a Peñarroya (11:55) pero aún no salió
    # (12:30): Peñarroya -> Los Blázquez no ha salido.
    ahora = datetime(2026, 9, 30, 12, 0, tzinfo=MADRID)
    c = query.consultar(CICLO_C, "penarroya", "los-blazquez", MIERCOLES, ahora=ahora)
    assert [s.ya_salio for s in c.salidas] == [False]
    ahora = datetime(2026, 9, 30, 12, 31, tzinfo=MADRID)
    c = query.consultar(CICLO_C, "penarroya", "los-blazquez", MIERCOLES, ahora=ahora)
    assert [s.ya_salio for s in c.salidas] == [True]


def test_cicloc_villanueva_del_rey_da_la_parada_de_cada_salida() -> None:
    c = query.consultar(CICLO_C, "cordoba", "villanueva-del-rey", MIERCOLES)
    paradas = {s.hora_salida.strftime("%H:%M"): s.parada_destino for s in c.salidas}
    assert paradas["10:30"] == "VRE"
    assert paradas["13:10"] == "VRC"


def test_cicloc_nota_a_solo_cuando_la_parada_es_origen_o_destino() -> None:
    # PVN (12:50A) es intermedia de Córdoba -> Los Blázquez: sin nota.
    c = query.consultar(CICLO_C, "cordoba", "los-blazquez", MIERCOLES)
    assert NOTA_APROXIMADA not in c.salidas[0].notas
    # Origen o destino en PVN: con nota.
    c = query.consultar(CICLO_C, "cordoba", "el-porvenir", MIERCOLES)
    assert any(NOTA_APROXIMADA in s.notas for s in c.salidas)
    c = query.consultar(CICLO_C, "el-porvenir", "los-blazquez", MIERCOLES)
    assert NOTA_APROXIMADA in c.salidas[0].notas


# ── Localidades pendientes (ciclo C2, P15/P32) ───────────────────────────────

PENDIENTES = loader.cargar(FIXTURES / "horarios_pendientes")


def test_consultar_origen_pendiente_lanza_value_error() -> None:
    with pytest.raises(ValueError, match="origen pendiente"):
        query.consultar(PENDIENTES, "aldea-a", "pueblo-b", date(2026, 9, 30))


def test_consultar_destino_pendiente_lanza_value_error() -> None:
    with pytest.raises(ValueError, match="destino pendiente"):
        query.consultar(PENDIENTES, "pueblo-a", "aldea-a", date(2026, 9, 30))


def test_destinos_desde_nunca_incluye_pendientes() -> None:
    for lid in PENDIENTES.modelo.localidades:
        destinos = query.destinos_desde(PENDIENTES, lid)
        assert not any(PENDIENTES.modelo.localidades[d].pendiente for d in destinos)
    assert set(query.destinos_desde(PENDIENTES, "pueblo-a")) == {"pueblo-b", "pueblo-c"}


# ── destinos_desde(..., linea=...) (P18) ────────────────────────────────


def test_destinos_desde_por_linea_solo_cuenta_esa_linea() -> None:
    todos = query.destinos_desde(HORARIOS, "pozoblanco")
    por_linea = {
        lid: query.destinos_desde(HORARIOS, "pozoblanco", lid) for lid in HORARIOS.lineas_pueblos
    }
    assert por_linea["belalcazar-pozoblanco"] == frozenset(
        {
            "alcaracejos",
            "belalcazar",
            "fuente-la-lancha",
            "hinojosa-del-duque",
            "villanueva-del-duque",
        }
    )
    assert por_linea["torrecampo-pozoblanco"] == frozenset({"pedroche", "torrecampo"})
    assert por_linea["adamuz-cordoba"] == frozenset()
    # la unión de las líneas es el resultado sin filtrar
    assert frozenset().union(*por_linea.values()) == todos


def test_destinos_desde_linea_inexistente_es_vacio() -> None:
    assert query.destinos_desde(HORARIOS, "pozoblanco", "no-existe") == frozenset()


def test_destinos_desde_cordoba_nunca_ofrece_rabanales_ni_alcolea() -> None:
    for linea in [None, *HORARIOS.lineas_pueblos]:
        destinos = query.destinos_desde(HORARIOS, "cordoba", linea)
        assert "campus-de-rabanales" not in destinos
        assert "alcolea" not in destinos


# ── Fase 1b-2: Peñarroya, Los Blázquez y Hornachuelos (datos reales) ──────────

JUEVES_INVIERNO = date(2026, 10, 1)  # jueves lectivo de invierno


def _salida_a_las(consulta: query.Consulta, hhmm: str) -> query.Salida:
    return next(s for s in consulta.salidas if s.hora_salida.strftime("%H:%M") == hhmm)


def test_cordoba_los_blazquez_una_sola_salida() -> None:
    c = query.consultar(HORARIOS, "cordoba", "los-blazquez", JUEVES_INVIERNO)
    assert _horas(c) == [("10:30", "13:20")]


def test_cordoba_penarroya_llegada_1155_y_fusion_con_badajoz() -> None:
    c = query.consultar(HORARIOS, "cordoba", "penarroya-pueblonuevo", JUEVES_INVIERNO)
    assert c.estado == "con_salidas"
    horas = [s.hora_salida.strftime("%H:%M") for s in c.salidas]
    assert horas.count("10:30") == 1
    s1030 = _salida_a_las(c, "10:30")
    assert s1030.hora_llegada.strftime("%H:%M") == "11:55"
    assert s1030.lineas == ("los-blazquez", "penarroya-cordoba")
    assert _salida_a_las(c, "15:00").lineas == ("badajoz-cordoba", "penarroya-cordoba")


def test_penarroya_los_blazquez_sale_a_las_1230() -> None:
    ahora = datetime(2026, 10, 1, 12, 0, tzinfo=MADRID)
    c = query.consultar(
        HORARIOS, "penarroya-pueblonuevo", "los-blazquez", JUEVES_INVIERNO, ahora=ahora
    )
    assert _horas(c) == [("12:30", "13:20")]
    assert c.salidas[0].ya_salio is False


def test_posadas_cordoba_no_para_en_el_pedrera() -> None:
    c = query.consultar(HORARIOS, "posadas", "cordoba", JUEVES_INVIERNO)
    pedrera = "No para en la parada de Pedrera (Posadas)."
    assert pedrera in _salida_a_las(c, "11:30").notas
    assert pedrera in _salida_a_las(c, "18:15").notas
    assert pedrera not in _salida_a_las(c, "08:30").notas


def test_almodovar_cordoba_sin_nota_de_el_pedrera() -> None:
    c = query.consultar(HORARIOS, "almodovar-del-rio", "cordoba", JUEVES_INVIERNO)
    assert c.estado == "con_salidas"
    assert all("Pedrera" not in n for s in c.salidas for n in s.notas)


def test_cordoba_villanueva_del_rey_pueblo_y_cruce() -> None:
    c = query.consultar(HORARIOS, "cordoba", "villanueva-del-rey", JUEVES_INVIERNO)
    paradas = {s.hora_salida.strftime("%H:%M"): s.parada_destino for s in c.salidas}
    assert paradas == {
        "10:30": "VRE",
        "13:10": "VRC",
        "15:00": "VRC",
        "18:30": "VRC",
        "20:00": "VRE",
    }


def test_badajoz_villanueva_del_rey_domingo_llega_al_cruce() -> None:
    c = query.consultar(HORARIOS, "badajoz", "villanueva-del-rey", date(2026, 10, 4))
    assert _horas(c) == [("14:30", "19:10")]
    assert c.salidas[0].parada_destino == "VRC"


def test_festivo_penarroya_cordoba_y_los_blazquez_sin_servicio() -> None:
    festivo = date(2026, 10, 12)  # lunes, Fiesta Nacional
    c = query.consultar(HORARIOS, "penarroya-pueblonuevo", "cordoba", festivo)
    assert _horas(c) == [("08:20", "09:40"), ("18:50", "20:10")]
    c = query.consultar(HORARIOS, "los-blazquez", "cordoba", festivo)
    assert c.estado == "sin_servicio"


def test_los_blazquez_cordoba_sabado_sin_servicio_y_siguiente_lunes() -> None:
    c = query.consultar(HORARIOS, "los-blazquez", "cordoba", date(2026, 10, 3))
    assert c.estado == "sin_servicio"
    assert c.siguiente_con_servicio == date(2026, 10, 5)


def test_fuente_obejuna_2150_solo_viernes_lectivo() -> None:
    viernes = query.consultar(HORARIOS, "cordoba", "fuente-obejuna", date(2026, 10, 2))
    jueves = query.consultar(HORARIOS, "cordoba", "fuente-obejuna", JUEVES_INVIERNO)
    assert ("20:00", "21:50") in _horas(viernes)
    assert ("20:00", "21:50") not in _horas(jueves)
    for dia in (date(2026, 10, 2), JUEVES_INVIERNO):
        c = query.consultar(HORARIOS, "cordoba", "penarroya-pueblonuevo", dia)
        assert "20:00" in [s.hora_salida.strftime("%H:%M") for s in c.salidas]


def test_hornachuelos_domingo_posadas_cordoba_invierno_y_verano() -> None:
    inv = query.consultar(HORARIOS, "posadas", "cordoba", date(2026, 10, 4))
    ver = query.consultar(HORARIOS, "posadas", "cordoba", date(2027, 7, 4))
    assert ("15:30", "16:20") in _horas(inv)
    assert ("12:30", "13:10") in _horas(ver)
    assert ("15:30", "16:20") not in _horas(ver)
    assert ("12:30", "13:10") not in _horas(inv)


# ── Actualización de negocio del 07/10/2026 (P29-P37) ───────────────────────

VIERNES_AGOSTO = date(2027, 8, 6)
DOMINGO_AGOSTO = date(2027, 8, 8)


def test_cordoba_los_mochos_lunes_laborable_misma_hora_que_almodovar() -> None:
    c = query.consultar(HORARIOS, "cordoba", "los-mochos", date(2026, 10, 5))
    assert c.estado == "con_salidas"
    assert _horas(c) == [("14:45", "15:15")]
    assert (c.salidas[0].parada_origen, c.salidas[0].parada_destino) == ("COR", "MOC")
    lunes = date(2026, 10, 5)
    almodovar = query.consultar(HORARIOS, "cordoba", "almodovar-del-rio", lunes)
    assert ("14:45", "15:15") in _horas(almodovar)


def test_rivero_cordoba_solo_en_los_viajes_que_pasan_por_rivero() -> None:
    c = query.consultar(HORARIOS, "rivero-de-posadas", "cordoba", date(2026, 10, 5))
    assert c.estado == "con_salidas"
    assert _horas(c) == [("06:35", "07:35"), ("09:30", "10:30"), ("14:55", "16:00")]
    posadas = query.consultar(HORARIOS, "posadas", "cordoba", date(2026, 10, 5))
    assert len(posadas.salidas) > len(c.salidas)


def test_badajoz_agosto_viernes_cordoba_badajoz_sin_servicio_y_zafra_si() -> None:
    c = query.consultar(HORARIOS, "cordoba", "badajoz", VIERNES_AGOSTO)
    assert c.estado == "sin_servicio"
    assert c.salidas == ()
    z = query.consultar(HORARIOS, "cordoba", "zafra", VIERNES_AGOSTO)
    assert z.estado == "con_salidas"
    assert _horas(z) == [("15:00", "18:15")]


def test_badajoz_agosto_domingo_sin_servicio() -> None:
    c = query.consultar(HORARIOS, "badajoz", "cordoba", DOMINGO_AGOSTO)
    assert c.estado == "sin_servicio"
    assert c.salidas == ()


def test_penarroya_agosto_domingo_sigue_con_los_viajes_de_domingo() -> None:
    c = query.consultar(HORARIOS, "cordoba", "penarroya-pueblonuevo", DOMINGO_AGOSTO)
    assert c.estado == "con_salidas"
    assert [s.hora_salida.strftime("%H:%M") for s in c.salidas] == ["14:45", "20:30"]


def test_respuesta_real_lleva_la_nota_de_horas_aproximadas_en_cada_salida() -> None:
    lunes = date(2026, 10, 5)
    c = query.consultar(HORARIOS, "cordoba", "villaviciosa-de-cordoba", lunes)
    assert c.salidas
    for s in c.salidas:
        assert s.notas.count("Horarios de paso aproximados.") == 1
