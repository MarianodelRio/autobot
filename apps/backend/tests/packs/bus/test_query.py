"""packs/bus/tests/test_query.py — motor de consulta.

Pruebas doradas contra `horarios_ficticios/` (red inventada, verificada a
mano contra `horarios_ficticios/lineas/*.yaml`) más pruebas sobre la mezcla
sintética tests/fixtures/horarios_motor/ para los casos especiales (a
demanda, viernes lectivo, no_circula, sin_datos, fusión) y
tests/fixtures/horarios_cicloC/ para llegada>salida y mismo autobús."""

from __future__ import annotations

from datetime import date, datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from packs.bus import loader, query
from packs.bus.calendario import InfoDia

FIXTURES = Path(__file__).parent / "fixtures"
HORARIOS_FICTICIOS = FIXTURES / "horarios_ficticios"

HORARIOS = loader.cargar(HORARIOS_FICTICIOS)
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


# ── Doradas: Pozoluengo <-> Riomayor ─────────────────────────────────────────


def test_pozoluengo_riomayor_miercoles_laborable() -> None:
    c = query.consultar(HORARIOS, "pozoluengo", "riomayor", date(2026, 9, 30))
    assert c.estado == "con_salidas"
    assert _horas(c) == [
        ("07:00", "07:45"),
        ("08:30", "09:15"),
        ("10:15", "11:00"),
        ("15:00", "15:45"),
        ("18:00", "18:45"),
    ]
    assert all(s.parada_origen == "POZ" and s.parada_destino == "RIO" for s in c.salidas)


def test_pozoluengo_riomayor_festivo_lunes() -> None:
    c = query.consultar(HORARIOS, "pozoluengo", "riomayor", date(2026, 10, 12))
    assert c.estado == "con_salidas"
    assert _info(c).es_festivo is True
    assert _horas(c) == [("08:15", "09:00"), ("15:15", "16:00"), ("17:45", "18:30")]


def test_pozoluengo_riomayor_festivo_en_sabado() -> None:
    c = query.consultar(HORARIOS, "pozoluengo", "riomayor", date(2027, 5, 1))
    assert c.estado == "con_salidas"
    assert _info(c).es_festivo is True
    # mismas 3 salidas que el festivo anterior, no el conjunto de sábado.
    assert _horas(c) == [("08:15", "09:00"), ("15:15", "16:00"), ("17:45", "18:30")]


def test_pozoluengo_riomayor_ya_salio() -> None:
    ahora = datetime(2026, 9, 30, 10, 30, tzinfo=MADRID)
    c = query.consultar(HORARIOS, "pozoluengo", "riomayor", date(2026, 9, 30), ahora=ahora)
    ya_salio = [s.ya_salio for s in c.salidas]
    assert ya_salio == [True, True, True, False, False]


def test_pozoluengo_carrascal_a_demanda_solo_en_la_ultima_salida() -> None:
    c = query.consultar(HORARIOS, "pozoluengo", "carrascal", date(2026, 9, 30))
    assert _horas(c) == [
        ("07:00", "07:20"),
        ("08:30", "08:50"),
        ("10:15", "10:35"),
        ("15:00", "15:20"),
        ("18:00", "18:20"),
    ]
    con_nota = [any("600 11 22 33" in n for n in s.notas) for s in c.salidas]
    assert con_nota == [False, False, False, False, True]


def test_carrascal_riomayor_lleva_a_demanda_y_llegada_a_la_estacion() -> None:
    c = query.consultar(HORARIOS, "carrascal", "riomayor", date(2026, 9, 30))
    ultima = c.salidas[-1]
    assert any("600 11 22 33" in n for n in ultima.notas)
    assert "Llega a la estación de autobuses de Riomayor." in ultima.notas
    assert c.salidas[0].notas == ()


# ── Riomayor <-> Montealto: a demanda y las tres temporadas ─────────────────


def test_montealto_invierno_laborable_dos_de_tres_a_demanda() -> None:
    c = query.consultar(HORARIOS, "riomayor", "montealto", date(2026, 9, 30))
    assert _horas(c) == [("08:00", "08:30"), ("13:00", "13:30"), ("17:30", "18:00")]
    a_demanda = [any("600 11 22 33" in n for n in s.notas) for s in c.salidas]
    assert a_demanda == [True, False, True]


def test_montealto_verano_horas_distintas_del_invierno() -> None:
    c = query.consultar(HORARIOS, "riomayor", "montealto", date(2027, 7, 14))
    assert _horas(c) == [("09:00", "09:30"), ("18:00", "18:30")]


def test_montealto_agosto_sin_servicio() -> None:
    c = query.consultar(HORARIOS, "riomayor", "montealto", date(2027, 8, 4))
    assert c.estado == "sin_servicio"


# ── Riomayor <-> Fuenteclara: "solo_si_viajeros" en una sola salida ─────────


def test_fuenteclara_solo_una_salida_con_la_nota_de_viajeros() -> None:
    c = query.consultar(HORARIOS, "riomayor", "fuenteclara", date(2026, 9, 30))
    assert _horas(c) == [("12:00", "13:35"), ("13:10", "15:10"), ("20:00", "21:45")]
    con_nota = [s for s in c.salidas if any("viajeros" in n for n in s.notas)]
    assert len(con_nota) == 1
    assert con_nota[0].hora_salida == time(20, 0)


# ── Riomayor <-> Ribazo: sin servicio el sábado y festivo, sin trayecto ─────


def test_ribazo_sabado_sin_servicio() -> None:
    c = query.consultar(HORARIOS, "riomayor", "ribazo", date(2026, 10, 3))
    assert c.estado == "sin_servicio"
    assert c.siguiente_con_servicio == date(2026, 10, 5)


def test_ribazo_festivo_lunes_sin_servicio() -> None:
    c = query.consultar(HORARIOS, "riomayor", "ribazo", date(2026, 10, 12))
    assert c.estado == "sin_servicio"
    assert c.siguiente_con_servicio == date(2026, 10, 13)


def test_pozoluengo_ribazo_sin_trayecto() -> None:
    c = query.consultar(HORARIOS, "pozoluengo", "ribazo", date(2026, 9, 30))
    assert c.estado == "sin_trayecto"
    assert c.siguiente_con_servicio is None


def test_pozoluengo_riomayor_fuera_de_calendario() -> None:
    c = query.consultar(HORARIOS, "pozoluengo", "riomayor", date(2028, 1, 2))
    assert c.estado == "sin_datos"
    assert c.fuera_de_calendario is True
    assert c.salidas == ()


def test_pozoluengo_riomayor_fuera_de_calendario_2027_10_01() -> None:
    # El curso 2027-28 no está cargado: vigencia termina el 31/08/2027.
    c = query.consultar(HORARIOS, "pozoluengo", "riomayor", date(2027, 10, 1))
    assert c.estado == "sin_datos"
    assert c.fuera_de_calendario is True


def test_origen_igual_destino_lanza_valueerror() -> None:
    with pytest.raises(ValueError):
        query.consultar(HORARIOS, "riomayor", "riomayor", date(2026, 9, 30))


def test_localidad_desconocida_lanza_valueerror() -> None:
    with pytest.raises(ValueError):
        query.consultar(HORARIOS, "riomayor", "no-existe", date(2026, 9, 30))


def test_destinos_desde_riomayor() -> None:
    destinos = query.destinos_desde(HORARIOS, "riomayor")
    assert destinos == frozenset(
        {
            "carrascal",
            "fuenteclara",
            "montealto",
            "odalla",
            "pozoluengo",
            "ribazo",
            "valdejunco",
            "villagrande-de-riomayor",
            "villagrande-del-soto",
        }
    )
    assert "riomayor" not in destinos


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
    assert any("600 55 55 55" in n for n in salida_demanda.notas)


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


def test_aviso_de_linea_se_repite_en_cada_salida_sin_marca_numerica() -> None:
    # linea-aproximada tiene un aviso de ámbito línea (hora_aproximada): debe
    # aparecer una vez en cada salida, sin marca numérica.
    c = query.consultar(MOTOR, "pueblo-r", "pueblo-s", date(2026, 9, 2))
    assert c.estado == "con_salidas"
    for s in c.salidas:
        assert s.notas.count("Horarios de paso aproximados.") == 1


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
    c = query.consultar(HORARIOS, "pozoluengo", "riomayor", date(2027, 1, 1))
    assert _info(c).nombre_festivo == "Año Nuevo"
    assert c.siguiente_con_servicio == date(2027, 1, 2)


def test_sin_servicio_general_siguiente_es_el_primer_dia_con_salidas() -> None:
    c = query.consultar(HORARIOS, "pozoluengo", "riomayor", date(2026, 12, 25))
    assert c.siguiente_con_servicio == date(2026, 12, 26)
    real = query.consultar(HORARIOS, "pozoluengo", "riomayor", date(2026, 12, 26))
    assert real.estado == "con_salidas"


def test_siguiente_con_servicio_desde_25_12_salta_el_fin_de_semana() -> None:
    # Riomayor -> Ribazo solo circula lunes-viernes: no tiene salidas el 25
    # (cierre general, viernes), el 26 (sábado) ni el 27/12/2026 (domingo):
    # el siguiente día con salidas es el lunes 28, saltando el fin de semana.
    c = query.consultar(HORARIOS, "riomayor", "ribazo", date(2026, 12, 25))
    assert c.estado == "sin_servicio"
    assert c.sin_servicio_general is True
    assert c.siguiente_con_servicio == date(2026, 12, 28)


def test_sin_servicio_general_no_pisa_sin_trayecto() -> None:
    c = query.consultar(HORARIOS, "pozoluengo", "ribazo", date(2026, 12, 25))
    assert c.estado == "sin_trayecto"
    assert c.sin_servicio_general is False


def test_sin_servicio_general_tiene_prioridad_sobre_la_vigencia() -> None:
    c = query.consultar(HORARIOS, "pozoluengo", "riomayor", date(2027, 12, 25))
    assert c.estado == "sin_servicio"
    assert c.sin_servicio_general is True
    assert c.fuera_de_calendario is False
    # sin calendario más allá de 31/08/2027 no se puede calcular el siguiente.
    assert c.siguiente_con_servicio is None
    assert c.info_dia is not None and _info(c).nombre_festivo is None


def test_dia_fuera_de_vigencia_que_no_es_general_sigue_siendo_sin_datos() -> None:
    c = query.consultar(HORARIOS, "pozoluengo", "riomayor", date(2027, 12, 24))
    assert c.estado == "sin_datos"
    assert c.fuera_de_calendario is True


# ── Festivos locales por línea (P03e) ───────────────────────────────────────

FESTIVO_LOCAL = loader.cargar(FIXTURES / "horarios_festivo_local")


def test_festivo_local_de_odalla_usa_las_salidas_de_festivos() -> None:
    # 14/10/2026 (miércoles, festivo local de Odalla) usa las mismas salidas
    # que domingos/festivos (09:00), no las de un miércoles normal.
    local = query.consultar(HORARIOS, "riomayor", "odalla", date(2026, 10, 14))
    normal = query.consultar(HORARIOS, "riomayor", "odalla", date(2026, 10, 21))
    assert local.estado == "con_salidas"
    assert _horas(local) == [("09:00", "09:30")]
    assert _horas(local) != _horas(normal)
    assert local.festivo_local == ("Fiesta local de Odalla", "odalla")
    assert _info(local).es_festivo is False  # InfoDia no cambia (P04)


def test_festivo_local_no_afecta_a_una_linea_que_no_toca_esa_localidad() -> None:
    # pozoluengo-riomayor no pasa por Odalla: el 14/10/2026 sigue siendo un
    # miércoles normal para esa línea.
    c = query.consultar(HORARIOS, "pozoluengo", "riomayor", date(2026, 10, 14))
    assert c.festivo_local is None
    assert _horas(c) == [
        ("07:00", "07:45"),
        ("08:30", "09:15"),
        ("10:15", "11:00"),
        ("15:00", "15:45"),
        ("18:00", "18:45"),
    ]


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


def test_odalla_festivo_local_viernes_lectivo_no_activa_solo_viernes_lectivo() -> None:
    # 16/10/2026 es viernes lectivo y festivo local de Odalla: la fila extra
    # ("solo_viernes_lectivo", 18:00) no debe activarse porque la línea pasa
    # a la clase "festivos"; solo sale la tabla de domingos-festivos.
    c = query.consultar(HORARIOS, "riomayor", "odalla", date(2026, 10, 16))
    assert c.estado == "con_salidas"
    assert _horas(c) == [("09:00", "09:30")]
    assert c.festivo_local == ("Feria de Odalla", "odalla")


# ── Trayectos no vendibles (P12b) ───────────────────────────────────────────

_NO_VENDIBLES = ("riomayor", "campoalto", "pinarnuevo")


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
        c = query.consultar(HORARIOS, "riomayor", "campoalto", fecha)
        assert c.estado == "no_vendible"
        assert c.sin_servicio_general is False


def test_es_no_vendible_es_falso_para_pares_normales() -> None:
    assert not query.es_no_vendible(HORARIOS, "riomayor", "pozoluengo")
    assert not query.es_no_vendible(HORARIOS, "campoalto", "odalla")


def test_destinos_desde_filtra_los_no_vendibles() -> None:
    assert "campoalto" not in query.destinos_desde(HORARIOS, "riomayor")
    assert "pinarnuevo" not in query.destinos_desde(HORARIOS, "riomayor")
    # las dos paradas de paso no venden entre sí en ninguna línea
    for linea in [None, *HORARIOS.lineas_pueblos]:
        destinos = query.destinos_desde(HORARIOS, "riomayor", linea)
        assert "campoalto" not in destinos
        assert "pinarnuevo" not in destinos


def test_destinos_desde_linea_inexistente_es_vacio() -> None:
    assert query.destinos_desde(HORARIOS, "riomayor", "no-existe") == frozenset()


# ── destinos_desde(..., linea=...) (P18) ────────────────────────────────


def test_destinos_desde_por_linea_solo_cuenta_esa_linea() -> None:
    todos = query.destinos_desde(HORARIOS, "riomayor")
    por_linea = {
        lid: query.destinos_desde(HORARIOS, "riomayor", lid) for lid in HORARIOS.lineas_pueblos
    }
    assert por_linea["pozoluengo-riomayor"] == frozenset({"carrascal", "pozoluengo"})
    assert por_linea["riomayor-fuenteclara"] == frozenset({"fuenteclara"})
    # Campoalto y Pinarnuevo son no vendibles desde Riomayor; Valdejunco no.
    assert por_linea["riomayor-pinarnuevo"] == frozenset({"valdejunco"})
    # la unión de las líneas es el resultado sin filtrar
    assert frozenset().union(*por_linea.values()) == todos


# ── Ciclo C1: llegada>salida y mismo autobús (fixture horarios_cicloC) ───────

CICLO_C = loader.cargar(FIXTURES / "horarios_cicloC")
MIERCOLES = date(2026, 9, 30)
NOTA_APROXIMADA = "Horarios de paso aproximados."


def test_cicloc_riomayor_penarroja_una_salida_con_las_dos_lineas() -> None:
    c = query.consultar(CICLO_C, "riomayor", "penarroja", MIERCOLES)
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


def test_cicloc_penarroja_los_alamos_sale_a_la_salida_de_penarroja() -> None:
    c = query.consultar(CICLO_C, "penarroja", "los-alamos", MIERCOLES)
    assert _horas(c) == [("12:30", "13:20")]
    assert c.salidas[0].lineas == ("larga",)
    assert c.salidas[0].duracion_min == 50


def test_cicloc_riomayor_los_alamos_una_sola_salida_de_punta_a_punta() -> None:
    c = query.consultar(CICLO_C, "riomayor", "los-alamos", MIERCOLES)
    assert _horas(c) == [("10:30", "13:20")]
    assert c.salidas[0].duracion_min == 170


def test_cicloc_ya_salio_usa_la_salida_no_la_llegada() -> None:
    # A las 12:00 el autobús ya llegó a Peñarroja (11:55) pero aún no salió
    # (12:30): Peñarroja -> Los Álamos no ha salido.
    ahora = datetime(2026, 9, 30, 12, 0, tzinfo=MADRID)
    c = query.consultar(CICLO_C, "penarroja", "los-alamos", MIERCOLES, ahora=ahora)
    assert [s.ya_salio for s in c.salidas] == [False]
    ahora = datetime(2026, 9, 30, 12, 31, tzinfo=MADRID)
    c = query.consultar(CICLO_C, "penarroja", "los-alamos", MIERCOLES, ahora=ahora)
    assert [s.ya_salio for s in c.salidas] == [True]


def test_cicloc_villanueva_del_pinar_da_la_parada_de_cada_salida() -> None:
    c = query.consultar(CICLO_C, "riomayor", "villanueva-del-pinar", MIERCOLES)
    paradas = {s.hora_salida.strftime("%H:%M"): s.parada_destino for s in c.salidas}
    assert paradas["10:30"] == "VRE"
    assert paradas["13:10"] == "VRC"


def test_cicloc_nota_a_solo_cuando_la_parada_es_origen_o_destino() -> None:
    # PVN (12:50A) es intermedia de Riomayor -> Los Álamos: sin nota.
    c = query.consultar(CICLO_C, "riomayor", "los-alamos", MIERCOLES)
    assert NOTA_APROXIMADA not in c.salidas[0].notas
    # Origen o destino en PVN: con nota.
    c = query.consultar(CICLO_C, "riomayor", "el-mirador", MIERCOLES)
    assert any(NOTA_APROXIMADA in s.notas for s in c.salidas)
    c = query.consultar(CICLO_C, "el-mirador", "los-alamos", MIERCOLES)
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
