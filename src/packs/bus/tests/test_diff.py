"""packs/bus/tests/test_diff.py — altas, bajas y cambios de hora, de observaciones, de
temporadas y de días, en lenguaje de negocio (buscaBus/design.md, sección 9).

Construye Modelo/Linea/Viaje/Paso/Temporada a mano: diff.py es puro y no toca
disco ni invoca formato.validar()."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import Any

from packs.bus import diff
from packs.bus.formato import Modelo
from packs.bus.modelo import (
    Calendario,
    Linea,
    Localidad,
    Observacion,
    Parada,
    Paso,
    Tabla,
    Temporada,
    Viaje,
)

PARADAS = {
    "AAA": Parada(codigo="AAA", nombre="Pueblo A", localidad="pueblo-a"),
    "BBB": Parada(codigo="BBB", nombre="Pueblo B", localidad="pueblo-b"),
    "CCC": Parada(codigo="CCC", nombre="Pueblo C", localidad="pueblo-c"),
    "DDD": Parada(codigo="DDD", nombre="Pueblo D", localidad="pueblo-d"),
}

OBSERVACIONES = {
    "entra_en_pueblo": Observacion(
        id="entra_en_pueblo",
        letra="P",
        tipo="aviso",
        ambitos=("parada",),
        texto="Este autobús entra en el pueblo.",
    ),
    "pasa_por_rivero": Observacion(
        id="pasa_por_rivero",
        letra=None,
        tipo="aviso",
        ambitos=("viaje",),
        texto="Pasa por Rivero de Posadas.",
    ),
}


def _modelo(lineas: dict[str, Linea], **extra: Any) -> Modelo:
    datos: dict[str, Any] = dict(
        localidades={},
        paradas=PARADAS,
        observaciones=OBSERVACIONES,
        lineas=lineas,
    )
    datos.update(extra)
    return Modelo(**datos)


def _tabla(
    linea: str = "l1",
    temporada: str = "anual",
    dias: str = "lunes-viernes",
    codigos: Sequence[str] = ("AAA", "BBB", "CCC"),
    posicion: int = 0,
) -> Tabla:
    return Tabla(
        linea=linea,
        temporada=temporada,
        dias=dias,
        paradas=tuple(codigos),
        posicion=posicion,
    )


def _viaje(
    linea: str = "l1",
    temporada: str = "anual",
    dias: str = "lunes-viernes",
    horas: Sequence[str] = ("08:00", "08:10", "08:20"),
    obs_viaje: Sequence[str] = (),
    pendientes: Sequence[str] = (),
    obs_por_paso: dict[str, Sequence[str]] | None = None,
    codigos: Sequence[str] = ("AAA", "BBB", "CCC"),
    tabla: Tabla | None = None,
    llegadas: dict[str, str] | None = None,
    bus: str | None = None,
) -> Viaje:
    """`llegadas`: {codigo: hora} para las paradas con espera; su hora de
    `horas` es entonces la salida."""
    obs_por_paso = obs_por_paso or {}
    llegadas = llegadas or {}
    pasos = tuple(
        Paso(
            parada=codigo,
            llegada=llegadas.get(codigo, hora),
            salida=hora,
            observaciones=tuple(obs_por_paso.get(codigo, ())),
        )
        for codigo, hora in zip(codigos, horas, strict=False)
    )
    if tabla is None:
        tabla = _tabla(linea=linea, temporada=temporada, dias=dias, codigos=codigos)
    return Viaje(
        linea=linea,
        temporada=temporada,
        dias=dias,
        tabla=tabla,
        observaciones=tuple(obs_viaje),
        pendientes=tuple(pendientes),
        pasos=pasos,
        bus=bus,
    )


def _linea(
    lid: str = "l1",
    nombre: str = "Línea 1",
    temporadas: tuple[Temporada, ...] = (Temporada(nombre="anual", rango="todo el año"),),
    dias: dict[str, dict[str, str]] | None = None,
    viajes: tuple[Viaje, ...] = (),
    nombre_corto: str | None = None,
    avisos: tuple[str, ...] = (),
) -> Linea:
    dias = (
        dias
        if dias is not None
        else {
            "anual": {
                "lunes": "horario",
                "martes": "horario",
                "miercoles": "horario",
                "jueves": "horario",
                "viernes": "horario",
                "sabado": "sin_servicio",
                "domingo": "sin_servicio",
                "festivos": "sin_servicio",
            }
        }
    )
    return Linea(
        id=lid,
        nombre=nombre,
        telefono_demanda=None,
        avisos=tuple(avisos),
        no_circula=(),
        temporadas=temporadas,
        dias=dias,
        pendientes=(),
        viajes=viajes,
        nombre_corto=nombre_corto,
    )


def test_sin_cambios() -> None:
    v = _viaje()
    linea = _linea(viajes=(v,))
    modelo = _modelo({"l1": linea})
    assert diff.comparar(modelo, modelo) == []


def test_viaje_anadido() -> None:
    v1 = _viaje(horas=("08:00", "08:10", "08:20"))
    v2 = _viaje(horas=("09:00", "09:10", "09:20"))
    anterior = _modelo({"l1": _linea(viajes=(v1,))})
    actual = _modelo({"l1": _linea(viajes=(v1, v2))})
    mensajes = diff.comparar(anterior, actual)
    assert any("viaje añadido" in m for m in mensajes)


def test_viaje_quitado() -> None:
    v1 = _viaje(horas=("08:00", "08:10", "08:20"))
    v2 = _viaje(horas=("09:00", "09:10", "09:20"))
    anterior = _modelo({"l1": _linea(viajes=(v1, v2))})
    actual = _modelo({"l1": _linea(viajes=(v1,))})
    mensajes = diff.comparar(anterior, actual)
    assert any("viaje quitado" in m for m in mensajes)


def test_hora_cambiada_en_un_paso() -> None:
    v_ant = _viaje(horas=("08:00", "08:10", "08:20"))
    v_act = _viaje(horas=("08:00", "08:15", "08:20"))
    anterior = _modelo({"l1": _linea(viajes=(v_ant,))})
    actual = _modelo({"l1": _linea(viajes=(v_act,))})
    mensajes = diff.comparar(anterior, actual)
    assert any("Pasa por Pueblo B: de las 08:10 a las 08:15" in m for m in mensajes)


def test_hora_cambiada_en_la_ultima_parada_dice_llega_a() -> None:
    v_ant = _viaje(horas=("08:00", "08:10", "08:20"))
    v_act = _viaje(horas=("08:00", "08:10", "08:25"))
    anterior = _modelo({"l1": _linea(viajes=(v_ant,))})
    actual = _modelo({"l1": _linea(viajes=(v_act,))})
    mensajes = diff.comparar(anterior, actual)
    assert any("Llega a Pueblo C: de las 08:20 a las 08:25" in m for m in mensajes)
    assert not any("Pasa por Pueblo C" in m or "Sale de Pueblo C" in m for m in mensajes)


def test_hora_cambiada_en_la_primera_parada_dice_sale_de() -> None:
    v_ant = _viaje(horas=("08:00", "08:10", "08:20"))
    v_act = _viaje(horas=("08:05", "08:10", "08:20"))
    anterior = _modelo({"l1": _linea(viajes=(v_ant,))})
    actual = _modelo({"l1": _linea(viajes=(v_act,))})
    mensajes = diff.comparar(anterior, actual)
    assert any("Sale de Pueblo A: de las 08:00 a las 08:05" in m for m in mensajes)


def test_quitar_un_viaje_de_un_grupo_no_genera_cambios_falsos() -> None:
    v1 = _viaje(horas=("07:00", "07:10", "07:20"))
    v2 = _viaje(horas=("08:00", "08:10", "08:20"))
    v3 = _viaje(horas=("09:00", "09:10", "09:20"))
    v4 = _viaje(horas=("10:00", "10:10", "10:20"))
    anterior = _modelo({"l1": _linea(viajes=(v1, v2, v3, v4))})
    actual = _modelo({"l1": _linea(viajes=(v1, v2, v4))})
    mensajes = diff.comparar(anterior, actual)
    mensajes_viaje_quitado = [m for m in mensajes if "viaje quitado" in m]
    assert len(mensajes_viaje_quitado) == 1
    assert "09:00" in mensajes_viaje_quitado[0]
    assert not any("de las" in m and "a las" in m for m in mensajes)


def test_mover_un_viaje_dos_horas_es_alta_y_baja() -> None:
    v_ant = _viaje(horas=("08:00", "08:10", "08:20"))
    v_act = _viaje(horas=("10:00", "10:10", "10:20"))
    anterior = _modelo({"l1": _linea(viajes=(v_ant,))})
    actual = _modelo({"l1": _linea(viajes=(v_act,))})
    mensajes = diff.comparar(anterior, actual)
    assert any("viaje añadido" in m for m in mensajes)
    assert any("viaje quitado" in m for m in mensajes)
    assert not any("de las" in m and "a las" in m for m in mensajes)


def test_anadir_una_parada_al_viaje() -> None:
    v_ant = _viaje(horas=("08:00", "08:20"), codigos=("AAA", "CCC"))
    v_act = _viaje(horas=("08:00", "08:10", "08:20"), codigos=("AAA", "BBB", "CCC"))
    anterior = _modelo({"l1": _linea(viajes=(v_ant,))})
    actual = _modelo({"l1": _linea(viajes=(v_act,))})
    mensajes = diff.comparar(anterior, actual)
    assert any("ahora para en Pueblo B a las 08:10" in m for m in mensajes)


def test_quitar_una_parada_del_viaje() -> None:
    v_ant = _viaje(horas=("08:00", "08:10", "08:20"), codigos=("AAA", "BBB", "CCC"))
    v_act = _viaje(horas=("08:00", "08:20"), codigos=("AAA", "CCC"))
    anterior = _modelo({"l1": _linea(viajes=(v_ant,))})
    actual = _modelo({"l1": _linea(viajes=(v_act,))})
    mensajes = diff.comparar(anterior, actual)
    assert any("ya no para en Pueblo B" in m for m in mensajes)


def test_reordenar_cabecera_sin_cambiar_horas_no_genera_cambios() -> None:
    # AAA y DDD (los extremos) se mantienen; solo se reordenan BBB y CCC en
    # medio, sin cambiar ninguna hora.
    tabla_ant = _tabla(codigos=("AAA", "BBB", "CCC", "DDD"))
    tabla_act = _tabla(codigos=("AAA", "CCC", "BBB", "DDD"))
    v_ant = _viaje(
        horas=("08:00", "08:10", "08:15", "08:20"),
        codigos=("AAA", "BBB", "CCC", "DDD"),
        tabla=tabla_ant,
    )
    v_act = _viaje(
        horas=("08:00", "08:15", "08:10", "08:20"),
        codigos=("AAA", "CCC", "BBB", "DDD"),
        tabla=tabla_act,
    )
    anterior = _modelo({"l1": _linea(viajes=(v_ant,))})
    actual = _modelo({"l1": _linea(viajes=(v_act,))})
    mensajes = diff.comparar(anterior, actual)
    assert mensajes == []


def test_observacion_anadida_en_paso() -> None:
    v_ant = _viaje(horas=("08:00", "08:10", "08:20"))
    v_act = _viaje(
        horas=("08:00", "08:10", "08:20"),
        obs_por_paso={"BBB": ("entra_en_pueblo",)},
    )
    anterior = _modelo({"l1": _linea(viajes=(v_ant,))})
    actual = _modelo({"l1": _linea(viajes=(v_act,))})
    mensajes = diff.comparar(anterior, actual)
    assert any(
        "en Pueblo B: se añade la observación «Este autobús entra en el pueblo.»" in m
        for m in mensajes
    )


def test_observacion_quitada_en_paso() -> None:
    v_ant = _viaje(
        horas=("08:00", "08:10", "08:20"),
        obs_por_paso={"BBB": ("entra_en_pueblo",)},
    )
    v_act = _viaje(horas=("08:00", "08:10", "08:20"))
    anterior = _modelo({"l1": _linea(viajes=(v_ant,))})
    actual = _modelo({"l1": _linea(viajes=(v_act,))})
    mensajes = diff.comparar(anterior, actual)
    assert any(
        "en Pueblo B: se quita la observación «Este autobús entra en el pueblo.»" in m
        for m in mensajes
    )


def test_observacion_anadida_en_viaje() -> None:
    v_ant = _viaje()
    v_act = _viaje(obs_viaje=("pasa_por_rivero",))
    anterior = _modelo({"l1": _linea(viajes=(v_ant,))})
    actual = _modelo({"l1": _linea(viajes=(v_act,))})
    mensajes = diff.comparar(anterior, actual)
    assert any("se añade la observación «Pasa por Rivero de Posadas.»" in m for m in mensajes)


def test_observacion_quitada_en_viaje() -> None:
    v_ant = _viaje(obs_viaje=("pasa_por_rivero",))
    v_act = _viaje()
    anterior = _modelo({"l1": _linea(viajes=(v_ant,))})
    actual = _modelo({"l1": _linea(viajes=(v_act,))})
    mensajes = diff.comparar(anterior, actual)
    assert any("se quita la observación «Pasa por Rivero de Posadas.»" in m for m in mensajes)


def test_temporada_rango_cambiada() -> None:
    anterior = _modelo(
        {"l1": _linea(temporadas=(Temporada(nombre="invierno", rango="01/09 - 22/06"),))}
    )
    actual = _modelo(
        {"l1": _linea(temporadas=(Temporada(nombre="invierno", rango="01/09 - 30/06"),))}
    )
    mensajes = diff.comparar(anterior, actual)
    assert any(
        "la temporada 'invierno' pasa de del 1 de septiembre al 22 de junio a "
        "del 1 de septiembre al 30 de junio" in m
        for m in mensajes
    )


def test_temporada_anadida() -> None:
    anterior = _modelo({"l1": _linea(temporadas=(Temporada(nombre="anual", rango="todo el año"),))})
    actual = _modelo(
        {
            "l1": _linea(
                temporadas=(
                    Temporada(nombre="anual", rango="todo el año"),
                    Temporada(nombre="verano", rango="23/06 - 31/08"),
                )
            )
        }
    )
    mensajes = diff.comparar(anterior, actual)
    assert any("se añade la temporada 'verano'" in m for m in mensajes)


def test_temporada_eliminada() -> None:
    anterior = _modelo(
        {
            "l1": _linea(
                temporadas=(
                    Temporada(nombre="anual", rango="todo el año"),
                    Temporada(nombre="verano", rango="23/06 - 31/08"),
                )
            )
        }
    )
    actual = _modelo({"l1": _linea(temporadas=(Temporada(nombre="anual", rango="todo el año"),))})
    mensajes = diff.comparar(anterior, actual)
    assert any("se quita la temporada 'verano'" in m for m in mensajes)


def test_estado_dia_cambiado_horario_a_sin_datos() -> None:
    dias_ant = {"anual": {"lunes": "horario"}}
    dias_act = {"anual": {"lunes": "sin_datos"}}
    anterior = _modelo({"l1": _linea(dias=dias_ant)})
    actual = _modelo({"l1": _linea(dias=dias_act)})
    mensajes = diff.comparar(anterior, actual)
    assert any("lunes: pasa de hay servicio a sin datos" in m for m in mensajes)
    # nunca se debe confundir "sin datos" con "sin servicio"
    assert not any("pasa de hay servicio a sin servicio" in m for m in mensajes)


def test_estado_dia_cambiado_sin_datos_a_sin_servicio() -> None:
    dias_ant = {"anual": {"lunes": "sin_datos"}}
    dias_act = {"anual": {"lunes": "sin_servicio"}}
    anterior = _modelo({"l1": _linea(dias=dias_ant)})
    actual = _modelo({"l1": _linea(dias=dias_act)})
    mensajes = diff.comparar(anterior, actual)
    assert any("lunes: pasa de sin datos a sin servicio" in m for m in mensajes)


def test_linea_nueva() -> None:
    anterior = _modelo({})
    actual = _modelo({"l1": _linea(nombre="Línea Nueva")})
    mensajes = diff.comparar(anterior, actual)
    assert mensajes == ["Línea nueva: Línea Nueva."]


def test_linea_eliminada() -> None:
    anterior = _modelo({"l1": _linea(nombre="Línea Vieja")})
    actual = _modelo({})
    mensajes = diff.comparar(anterior, actual)
    assert mensajes == ["Línea eliminada: Línea Vieja."]


# ── llegada>salida y bus: (ciclo C1) ────────────────────────────────────────


def _comparar_un_viaje(v_ant: Viaje, v_act: Viaje) -> list[str]:
    anterior = _modelo({"l1": _linea(viajes=(v_ant,))})
    actual = _modelo({"l1": _linea(viajes=(v_act,))})
    return diff.comparar(anterior, actual)


def test_cambio_de_la_salida_en_una_celda_con_espera() -> None:
    v_ant = _viaje(horas=("08:00", "08:45", "09:30"), llegadas={"BBB": "08:10"})
    v_act = _viaje(horas=("08:00", "09:00", "09:30"), llegadas={"BBB": "08:10"})
    mensajes = _comparar_un_viaje(v_ant, v_act)
    assert mensajes == [
        "Línea 1, anual, lunes a viernes: en Pueblo B, la salida pasa de las 08:45 a las 09:00."
    ]


def test_cambio_de_la_llegada_en_una_celda_con_espera() -> None:
    v_ant = _viaje(horas=("08:00", "08:45", "09:30"), llegadas={"BBB": "08:10"})
    v_act = _viaje(horas=("08:00", "08:45", "09:30"), llegadas={"BBB": "08:20"})
    mensajes = _comparar_un_viaje(v_ant, v_act)
    assert mensajes == [
        "Línea 1, anual, lunes a viernes: en Pueblo B, la llegada pasa de las 08:10 a las 08:20."
    ]


def test_cambio_de_llegada_y_salida_da_dos_mensajes() -> None:
    v_ant = _viaje(horas=("08:00", "08:45", "09:30"), llegadas={"BBB": "08:10"})
    v_act = _viaje(horas=("08:00", "08:50", "09:30"), llegadas={"BBB": "08:15"})
    mensajes = _comparar_un_viaje(v_ant, v_act)
    assert len(mensajes) == 2
    assert any("la llegada pasa de las 08:10 a las 08:15" in m for m in mensajes)
    assert any("la salida pasa de las 08:45 a las 08:50" in m for m in mensajes)


def test_celda_simple_que_pasa_a_llegada_y_salida() -> None:
    v_ant = _viaje(horas=("08:00", "08:10", "09:30"))
    v_act = _viaje(horas=("08:00", "08:45", "09:30"), llegadas={"BBB": "08:10"})
    mensajes = _comparar_un_viaje(v_ant, v_act)
    assert mensajes == [
        "Línea 1, anual, lunes a viernes: en Pueblo B, ahora llega a las 08:10 "
        "y sale a las 08:45 (antes 08:10)."
    ]


def test_llegada_y_salida_que_pasan_a_celda_simple() -> None:
    v_ant = _viaje(horas=("08:00", "08:45", "09:30"), llegadas={"BBB": "08:10"})
    v_act = _viaje(horas=("08:00", "08:10", "09:30"))
    mensajes = _comparar_un_viaje(v_ant, v_act)
    assert len(mensajes) == 1
    assert "en Pueblo B, ahora llega y sale a las 08:10" in mensajes[0]


def test_parada_nueva_con_espera_se_describe_con_las_dos_horas() -> None:
    v_ant = _viaje(horas=("08:00", "09:30"), codigos=("AAA", "CCC"))
    v_act = _viaje(
        horas=("08:00", "08:45", "09:30"),
        llegadas={"BBB": "08:10"},
        tabla=_tabla(codigos=("AAA", "CCC")),
    )
    mensajes = _comparar_un_viaje(v_ant, v_act)
    assert any(
        "ahora para en Pueblo B: llega a las 08:10 y sale a las 08:45" in m for m in mensajes
    )


def test_emparejado_de_viajes_usa_la_salida() -> None:
    # La llegada cambia mucho pero la salida (>30 min) no: sigue siendo el
    # mismo viaje y se describe como un cambio de llegada, no alta+baja.
    v_ant = _viaje(horas=("08:00", "08:45", "09:30"), llegadas={"BBB": "08:10"})
    v_act = _viaje(horas=("08:00", "08:45", "09:30"), llegadas={"BBB": "08:40"})
    mensajes = _comparar_un_viaje(v_ant, v_act)
    assert not any("añadido" in m or "quitado" in m for m in mensajes)


def test_alta_de_bus() -> None:
    mensajes = _comparar_un_viaje(_viaje(), _viaje(bus="cor-1030"))
    assert mensajes == [
        "Línea 1, anual, lunes a viernes: ahora se marca como el mismo autobús "
        "que otros viajes ('cor-1030')."
    ]


def test_baja_de_bus() -> None:
    mensajes = _comparar_un_viaje(_viaje(bus="cor-1030"), _viaje())
    assert mensajes == [
        "Línea 1, anual, lunes a viernes: ya no se marca como el mismo autobús "
        "que otros viajes ('cor-1030')."
    ]


def test_cambio_de_bus() -> None:
    mensajes = _comparar_un_viaje(_viaje(bus="a-1"), _viaje(bus="b-2"))
    assert mensajes == [
        "Línea 1, anual, lunes a viernes: el identificador de autobús pasa de 'a-1' a 'b-2'."
    ]


def test_cambio_de_titulo_en_el_bot() -> None:
    v = _viaje()
    antes = _modelo({"l1": _linea(nombre="Línea larga de prueba", viajes=(v,))})
    despues = _modelo(
        {"l1": _linea(nombre="Línea larga de prueba", nombre_corto="Corta", viajes=(v,))}
    )
    assert diff.comparar(antes, despues) == [
        'Línea larga de prueba: en el bot se mostrará como "Corta" (antes "Línea larga de prueba")'
    ]


def test_mismo_titulo_no_genera_mensaje() -> None:
    v = _viaje()
    modelo = _modelo({"l1": _linea(nombre_corto="Corta", viajes=(v,))})
    assert diff.comparar(modelo, modelo) == []


# ── Texto de observaciones, avisos de línea, calendario, paradas ─────────────


def test_observacion_quitada_del_modelo_usa_el_texto_anterior_o_el_id() -> None:
    v_ant = _viaje(obs_viaje=("pasa_por_rivero",))
    v_act = _viaje()
    anterior = _modelo({"l1": _linea(viajes=(v_ant,))})
    actual = _modelo({"l1": _linea(viajes=(v_act,))}, observaciones={})
    frases = diff.comparar(anterior, actual)
    assert any("«Pasa por Rivero de Posadas.»" in m for m in frases)
    ambos_vacios_ant = _modelo({"l1": _linea(viajes=(v_ant,))}, observaciones={})
    frases = diff.comparar(ambos_vacios_ant, actual)
    assert any("«pasa_por_rivero»" in m for m in frases)


def _lineas_con_aviso(n: int, con_aviso: bool) -> dict[str, Linea]:
    return {
        f"l{i}": _linea(
            lid=f"l{i}",
            nombre=f"Línea {i}",
            avisos=("pasa_por_rivero",) if con_aviso else (),
        )
        for i in range(1, n + 1)
    }


def test_aviso_en_tres_lineas_se_agrupa_en_una_frase() -> None:
    anterior = _modelo(_lineas_con_aviso(3, False))
    actual = _modelo(_lineas_con_aviso(3, True))
    assert diff.comparar(anterior, actual) == [
        "Se añade el aviso «Pasa por Rivero de Posadas.» a 3 líneas: Línea 1, Línea 2, Línea 3."
    ]
    assert diff.comparar(actual, anterior) == [
        "Se quita el aviso «Pasa por Rivero de Posadas.» a 3 líneas: Línea 1, Línea 2, Línea 3."
    ]


def test_aviso_en_menos_de_tres_lineas_va_linea_a_linea() -> None:
    anterior = _modelo(_lineas_con_aviso(2, False))
    actual = _modelo(_lineas_con_aviso(2, True))
    assert diff.comparar(anterior, actual) == [
        "Línea 1: se añade el aviso «Pasa por Rivero de Posadas.».",
        "Línea 2: se añade el aviso «Pasa por Rivero de Posadas.».",
    ]


def test_aviso_agrupado_no_se_repite_por_linea_y_el_bloque_general_va_primero() -> None:
    anterior = _modelo(_lineas_con_aviso(3, False))
    lineas = _lineas_con_aviso(3, True)
    lineas["l1"] = _linea(
        lid="l1",
        nombre="Línea 1",
        avisos=("pasa_por_rivero",),
        viajes=(_viaje(),),
    )
    anterior = _modelo({**_lineas_con_aviso(3, False), "l1": _linea(lid="l1", nombre="Línea 1")})
    actual = _modelo(lineas, localidades={"x": Localidad(id="x", nombre="Nueva")})
    mensajes = diff.comparar(anterior, actual)
    assert mensajes[0] == "Se añade la localidad «Nueva»."
    assert mensajes[1].startswith("Se añade el aviso ")
    assert sum("el aviso" in m for m in mensajes) == 1


def test_avisos_no_circula_y_telefono_no_generan_frases() -> None:
    ant = _linea()
    act = _linea()
    object.__setattr__(act, "no_circula", ("agosto",))
    object.__setattr__(act, "telefono_demanda", "957 00 00 00")
    assert diff.comparar(_modelo({"l1": ant}), _modelo({"l1": act})) == []


def _calendario(**cambios: Any) -> Calendario:
    base: dict[str, Any] = dict(
        vigencia_inicio=date(2026, 1, 1),
        vigencia_fin=date(2027, 8, 31),
        festivos={date(2026, 1, 1): "Año Nuevo"},
        inicio_clases=date(2026, 9, 14),
        fin_clases=date(2027, 6, 22),
        vacaciones=(),
        no_lectivos=(),
    )
    base.update(cambios)
    return Calendario(**base)


def test_calendario_none_no_rompe_ni_genera_frases() -> None:
    sin = _modelo({"l1": _linea()})
    con = _modelo({"l1": _linea()}, calendario=_calendario())
    assert diff.comparar(sin, con) == []
    assert diff.comparar(con, sin) == []
    assert diff.comparar(sin, sin) == []


def test_calendario_cambios() -> None:
    ant = _modelo({}, calendario=_calendario())
    act = _modelo(
        {},
        localidades={"cor": Localidad(id="cor", nombre="Córdoba")},
        calendario=_calendario(
            festivos={date(2026, 12, 25): "Navidad"},
            inicio_clases=date(2026, 9, 15),
            fin_clases=date(2027, 6, 23),
            vigencia_inicio=date(2026, 2, 1),
            vigencia_fin=date(2027, 9, 30),
            sin_servicio_todas_las_lineas=frozenset({(12, 25)}),
            festivos_locales={"cor": {date(2026, 9, 8): "Fuensanta"}},
        ),
    )
    mensajes = diff.comparar(ant, act)
    assert "Se añade el festivo «Navidad» (25 de diciembre de 2026)." in mensajes
    assert "Se quita el festivo «Año Nuevo» (1 de enero de 2026)." in mensajes
    assert "Se añade el festivo local «Fuensanta» en Córdoba (8 de septiembre de 2026)." in mensajes
    assert "Se añade el 25 de diciembre como día sin servicio en ninguna línea." in mensajes
    assert (
        "El inicio de las clases pasa del 14 de septiembre de 2026 al 15 de "
        "septiembre de 2026." in mensajes
    )
    assert any(m.startswith("El fin de las clases pasa") for m in mensajes)
    assert any(m.startswith("El calendario empieza a valer pasa") for m in mensajes)
    assert any(m.startswith("El calendario deja de valer pasa") for m in mensajes)
    # vacaciones y no lectivos no generan frases
    ant2 = _modelo({}, calendario=_calendario())
    act2 = _modelo(
        {},
        calendario=_calendario(
            vacaciones=((date(2026, 12, 23), date(2027, 1, 7)),), no_lectivos=(date(2026, 10, 30),)
        ),
    )
    assert diff.comparar(ant2, act2) == []


def test_paradas_localidades_alias_y_no_vendibles() -> None:
    cor = Localidad(id="cor", nombre="Córdoba", alias=("cba",))
    poz = Localidad(id="poz", nombre="Pozoblanco")
    ant = _modelo(
        {},
        localidades={"cor": cor, "poz": poz},
        paradas={
            "AAA": Parada(codigo="AAA", nombre="Estación", localidad="cor"),
        },
    )
    act = _modelo(
        {},
        localidades={
            "cor": Localidad(id="cor", nombre="Córdoba capital", alias=("cordoba",)),
            "riv": Localidad(id="riv", nombre="Rivero de Posadas"),
        },
        paradas={
            "AAA": Parada(codigo="AAA", nombre="Estación AVE", localidad="cor"),
            "RIV": Parada(codigo="RIV", nombre="Rivero de Posadas", localidad="riv"),
        },
        no_vendibles=frozenset({frozenset({"cor", "riv"})}),
    )
    mensajes = diff.comparar(ant, act)
    assert "Se añade la localidad «Rivero de Posadas»." in mensajes
    assert "Se quita la localidad «Pozoblanco»." in mensajes
    assert "La localidad «Córdoba» pasa a llamarse «Córdoba capital»." in mensajes
    assert "Córdoba capital: se añade el alias «cordoba»." in mensajes
    assert "Córdoba capital: se quita el alias «cba»." in mensajes
    assert "Se añade la parada «Rivero de Posadas» (localidad Rivero de Posadas)." in mensajes
    assert "La parada «Estación» pasa a llamarse «Estación AVE»." in mensajes
    assert "Ya no se venden billetes entre Córdoba capital y Rivero de Posadas." in mensajes
    inversa = diff.comparar(act, ant)
    assert "Se quita la parada «Rivero de Posadas»." in inversa
    assert "Vuelven a venderse billetes entre Córdoba capital y Rivero de Posadas." in inversa


def test_texto_de_observacion_cambiado() -> None:
    nueva = {
        "entra_en_pueblo": Observacion(
            id="entra_en_pueblo",
            letra="P",
            tipo="aviso",
            ambitos=("parada",),
            texto="Entra en el pueblo.",
        )
    }
    ant = _modelo({})
    act = _modelo({}, observaciones=nueva)
    mensajes = diff.comparar(ant, act)
    assert (
        "El texto de la observación «Este autobús entra en el pueblo.» pasa a "
        "«Entra en el pueblo.»." in mensajes
    )
    # id renombrado = una quitada y una añadida, sin frase de cambio de texto
    renombrada = {
        "otro_id": Observacion(
            id="otro_id",
            letra="P",
            tipo="aviso",
            ambitos=("parada",),
            texto="Entra en el pueblo.",
        )
    }
    assert not any(
        m.startswith("El texto de la observación")
        for m in diff.comparar(ant, _modelo({}, observaciones=renombrada))
    )
