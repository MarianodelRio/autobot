"""packs/bus/tests/test_conversation.py — flujo completo y casos borde."""

from collections.abc import Callable
from datetime import date, timedelta
from typing import Any

import pytest

from packs.bus.datos import Datos
from packs.bus.matcher import Coincidencia
from packs.bus.tests.compat import NEGOCIO_TELEFONO, Conv, MockWA

Freeze = Callable[..., None]

HOY = date(2026, 9, 23)  # miércoles, dentro de vigencia


def _last_interactive(mock_wa: MockWA) -> dict[str, Any]:
    payload: dict[str, Any] = mock_wa["interactive"].call_args[0][1]
    return payload


def _last_text(mock_wa: MockWA) -> str:
    return str(mock_wa["text"].call_args[0][1])


def _button_ids(payload: dict[str, Any]) -> list[str]:
    return [b["reply"]["id"] for b in payload["interactive"]["action"]["buttons"]]


def _row_ids(payload: dict[str, Any]) -> list[str]:
    return [
        row["id"]
        for section in payload["interactive"]["action"]["sections"]
        for row in section["rows"]
    ]


def test_happy_path(conv: Conv, mock_wa: MockWA, freeze_calendario: Freeze) -> None:
    freeze_calendario(HOY)
    phone = "34600000001"
    conv.handle_message(phone, phone, None, "menu_horarios")
    assert "pueblo" in _last_interactive(mock_wa)["interactive"]["body"]["text"].lower()

    conv.handle_message(phone, phone, None, "loc:pozoblanco")
    payload = _last_interactive(mock_wa)
    assert "Desde Pozoblanco" in payload["interactive"]["header"]["text"]

    conv.handle_message(phone, phone, None, "loc:cordoba")
    payload = _last_interactive(mock_wa)
    assert payload["interactive"]["type"] == "list"
    assert any(r.startswith("dia:") for r in _row_ids(payload))

    manana = (HOY + timedelta(days=1)).isoformat()
    conv.handle_message(phone, phone, None, f"dia:{manana}")
    payload = _last_interactive(mock_wa)
    assert payload["interactive"]["type"] == "button"
    assert set(_button_ids(payload)) == {"otro_dia", "vuelta", "otra_consulta"}
    assert "Pozoblanco" in payload["interactive"]["body"]["text"]


def test_villafranca_ambiguity_always_asks(
    conv: Conv, mock_wa: MockWA, freeze_calendario: Freeze
) -> None:
    freeze_calendario(HOY)
    phone = "34600000002"
    conv.handle_message(phone, phone, None, "menu_horarios")
    conv.handle_message(phone, phone, "villafranca", None)
    payload = _last_interactive(mock_wa)
    ids = (
        set(_row_ids(payload))
        if payload["interactive"]["type"] == "list"
        else set(_button_ids(payload))
    )
    assert "loc:villafranca-de-cordoba" in ids
    assert "loc:villafranca-de-los-barros" in ids
    # no debe ser una confirmación sí/no
    assert not (
        payload["interactive"]["type"] == "button" and set(_button_ids(payload)) == {"si", "no"}
    )


def test_villafranca_with_typo_still_asks(
    conv: Conv, mock_wa: MockWA, freeze_calendario: Freeze
) -> None:
    freeze_calendario(HOY)
    phone = "34600000003"
    conv.handle_message(phone, phone, None, "menu_horarios")
    conv.handle_message(phone, phone, "villafranka", None)
    payload = _last_interactive(mock_wa)
    ids = (
        set(_row_ids(payload))
        if payload["interactive"]["type"] == "list"
        else set(_button_ids(payload))
    )
    assert "loc:villafranca-de-cordoba" in ids
    assert "loc:villafranca-de-los-barros" in ids


def test_errata_confirms(conv: Conv, mock_wa: MockWA, freeze_calendario: Freeze) -> None:
    freeze_calendario(HOY)
    phone = "34600000004"
    conv.handle_message(phone, phone, None, "menu_horarios")
    conv.handle_message(phone, phone, "pozoblnco", None)
    payload = _last_interactive(mock_wa)
    assert payload["interactive"]["type"] == "button"
    assert set(_button_ids(payload)) == {"si", "no"}
    assert "Pozoblanco" in payload["interactive"]["body"]["text"]

    conv.handle_message(phone, phone, None, "si")
    payload = _last_interactive(mock_wa)
    assert "Desde Pozoblanco" in payload["interactive"]["header"]["text"]


def test_sin_coincidencia_logs_no_phone(
    conv: Conv, mock_wa: MockWA, freeze_calendario: Freeze, caplog: pytest.LogCaptureFixture
) -> None:
    freeze_calendario(HOY)
    phone = "34600000005"
    conv.handle_message(phone, phone, None, "menu_horarios")
    import logging

    caplog.set_level(logging.INFO, logger="packs.bus")
    conv.handle_message(phone, phone, "xyzxyzxyz", None)
    assert any("[NO_RECONOCIDO]" in r.message for r in caplog.records)
    for r in caplog.records:
        if "[NO_RECONOCIDO]" in r.message:
            assert phone not in r.message


def test_origen_igual_destino(conv: Conv, mock_wa: MockWA, freeze_calendario: Freeze) -> None:
    freeze_calendario(HOY)
    phone = "34600000006"
    conv.handle_message(phone, phone, None, "menu_horarios")
    conv.handle_message(phone, phone, None, "loc:pozoblanco")
    conv.handle_message(phone, phone, None, "loc:pozoblanco")
    payload = _last_interactive(mock_wa)
    assert "distinto" in payload["interactive"]["body"]["text"].lower()


def test_sin_trayecto_directo(conv: Conv, mock_wa: MockWA, freeze_calendario: Freeze) -> None:
    freeze_calendario(HOY)
    phone = "34600000007"
    conv.handle_message(phone, phone, None, "menu_horarios")
    conv.handle_message(phone, phone, None, "loc:pozoblanco")
    conv.handle_message(phone, phone, "badajoz", None)
    payload = _last_interactive(mock_wa)
    body = payload["interactive"]["body"]["text"].lower()
    assert "trayecto" in body or "no hay" in body


def test_fecha_pasada(conv: Conv, mock_wa: MockWA, freeze_calendario: Freeze) -> None:
    freeze_calendario(HOY)
    phone = "34600000008"
    conv.handle_message(phone, phone, None, "menu_horarios")
    conv.handle_message(phone, phone, None, "loc:pozoblanco")
    conv.handle_message(phone, phone, None, "loc:cordoba")
    conv.handle_message(phone, phone, None, "otra_fecha")
    conv.handle_message(phone, phone, "20/09", None)
    all_texts = " ".join(c.args[1] for c in mock_wa["text"].call_args_list)
    assert "pasado" in all_texts.lower()


def test_hoy_sin_salidas_ofrece_mañana(
    conv: Conv, mock_wa: MockWA, freeze_calendario: Freeze
) -> None:
    freeze_calendario(HOY, hora=(23, 0))
    phone = "34600000009"
    conv.handle_message(phone, phone, None, "menu_horarios")
    conv.handle_message(phone, phone, None, "loc:pozoblanco")
    conv.handle_message(phone, phone, None, "loc:cordoba")
    conv.handle_message(phone, phone, None, f"dia:{HOY.isoformat()}")
    payload = _last_interactive(mock_wa)
    assert payload["interactive"]["type"] == "button"
    ids = _button_ids(payload)
    assert any(i.startswith("dia:") for i in ids)
    assert "ya no quedan" in payload["interactive"]["body"]["text"].lower()


def test_estado_caducado_vuelve_al_menu(
    conv: Conv, mock_wa: MockWA, freeze_calendario: Freeze
) -> None:
    freeze_calendario(HOY)
    phone = "34600000010"
    conv.handle_message(phone, phone, None, "menu_horarios")
    conv.handle_message(phone, phone, None, "loc:pozoblanco")
    # En Autobot la caducidad (30 min) la aplica la plataforma: pasada, el siguiente
    # mensaje empieza en el menú.
    freeze_calendario(HOY, hora=(0, 31))
    conv.handle_message(phone, phone, None, "loc:cordoba")
    assert conv._get(phone).step == conv.flujo.MENU
    assert "necesitas" in _last_interactive(mock_wa)["interactive"]["body"]["text"].lower()


def test_unknown_id_goes_to_menu(conv: Conv, mock_wa: MockWA, freeze_calendario: Freeze) -> None:
    freeze_calendario(HOY)
    phone = "34600000011"
    # Estado fresco (MENU): un id desconocido nunca debe tratarse como si
    # fuera válido en otro paso — vuelve al menú.
    conv.handle_message(phone, phone, None, "dia:2020-01-01")
    payload = _last_interactive(mock_wa)
    assert "necesitas" in payload["interactive"]["body"]["text"].lower()


def test_escape_words_return_to_menu(
    conv: Conv, mock_wa: MockWA, freeze_calendario: Freeze
) -> None:
    freeze_calendario(HOY)
    phone = "34600000012"
    conv.handle_message(phone, phone, None, "menu_horarios")
    conv.handle_message(phone, phone, "menu", None)
    payload = _last_interactive(mock_wa)
    assert "necesitas" in payload["interactive"]["body"]["text"].lower()


def test_one_outgoing_message_per_input(
    conv: Conv, mock_wa: MockWA, freeze_calendario: Freeze
) -> None:
    freeze_calendario(HOY)
    phone = "34600000013"
    conv.handle_message(phone, phone, None, "menu_horarios")
    total_before = mock_wa["text"].call_count + mock_wa["interactive"].call_count
    conv.handle_message(phone, phone, None, "loc:pozoblanco")
    total_after = mock_wa["text"].call_count + mock_wa["interactive"].call_count
    assert total_after - total_before == 1


def test_unsupported_media_type_gives_fallback(
    conv: Conv, mock_wa: MockWA, freeze_calendario: Freeze
) -> None:
    freeze_calendario(HOY)
    phone = "34600000014"
    conv.handle_message(phone, phone, conv.UNKNOWN_INPUT, None)
    assert mock_wa["text"].called


# ── Casos borde de 4.8 (correcciones fase 4, docs/rds_fase4_correcciones.md) ─


def _n_calls(mock_wa: MockWA) -> int:
    return mock_wa["text"].call_count + mock_wa["interactive"].call_count


def test_dia_sin_servicio_ofrece_siguiente(
    conv: Conv, mock_wa: MockWA, freeze_calendario: Freeze, datos_motor: Datos
) -> None:
    sabado = date(2026, 9, 26)
    freeze_calendario(sabado)
    phone = "34600000101"
    conv.handle_message(phone, phone, None, "menu_horarios")
    conv.handle_message(phone, phone, "pueblo a", None)
    conv.handle_message(phone, phone, "pueblo b", None)
    total_before = _n_calls(mock_wa)
    conv.handle_message(phone, phone, None, f"dia:{sabado.isoformat()}")
    assert _n_calls(mock_wa) - total_before == 1
    payload = _last_interactive(mock_wa)
    body = payload["interactive"]["body"]["text"].lower()
    assert "no hay servicio" in body
    ids = _button_ids(payload)
    siguiente = date(2026, 9, 28)  # lunes: próximo día con servicio
    assert f"dia:{siguiente.isoformat()}" in ids

    total_before = _n_calls(mock_wa)
    conv.handle_message(phone, phone, None, f"dia:{siguiente.isoformat()}")
    assert _n_calls(mock_wa) - total_before == 1
    payload = _last_interactive(mock_wa)
    assert "no hay servicio" not in payload["interactive"]["body"]["text"].lower()


def test_sin_servicio_a_mas_de_7_dias_ofrece_boton_dia(
    conv: Conv, mock_wa: MockWA, freeze_calendario: Freeze, datos_motor: Datos
) -> None:
    freeze_calendario(HOY)  # 23/09/2026, dentro del no_circula [septiembre]
    phone = "34600000102"
    conv.handle_message(phone, phone, None, "menu_horarios")
    conv.handle_message(phone, phone, "pueblo p", None)
    conv.handle_message(phone, phone, "pueblo q", None)
    total_before = _n_calls(mock_wa)
    conv.handle_message(phone, phone, None, f"dia:{HOY.isoformat()}")
    assert _n_calls(mock_wa) - total_before == 1
    payload = _last_interactive(mock_wa)
    body = payload["interactive"]["body"]["text"]
    assert "Ese día no hay servicio en este trayecto." in body
    assert "jueves 01/10" in body
    ids = _button_ids(payload)
    assert "dia:2026-10-01" in ids
    for b in payload["interactive"]["action"]["buttons"]:
        assert len(b["reply"]["title"]) <= 20


def test_sin_servicio_sin_dia_con_salidas_en_45_dias_da_telefono(
    conv: Conv, mock_wa: MockWA, freeze_calendario: Freeze, datos_motor: Datos
) -> None:
    agosto = date(2026, 8, 1)
    freeze_calendario(agosto)
    phone = "34600000104"
    conv.handle_message(phone, phone, None, "menu_horarios")
    conv.handle_message(phone, phone, "pueblo p", None)
    conv.handle_message(phone, phone, "pueblo q", None)
    conv.handle_message(phone, phone, None, f"dia:{agosto.isoformat()}")
    payload = _last_interactive(mock_wa)
    body = payload["interactive"]["body"]["text"]
    assert "no hay salidas" in body.lower()
    assert "957" in body or "tel" in body.lower() or "📞" in body
    assert not any(i.startswith("dia:") for i in _button_ids(payload))


def test_dia_sin_datos_no_es_sin_servicio(
    conv: Conv, mock_wa: MockWA, freeze_calendario: Freeze, datos_motor: Datos
) -> None:
    freeze_calendario(HOY)
    phone = "34600000103"
    conv.handle_message(phone, phone, None, "menu_horarios")
    conv.handle_message(phone, phone, "pueblo g", None)
    total_before = _n_calls(mock_wa)
    conv.handle_message(phone, phone, "pueblo h", None)
    assert _n_calls(mock_wa) - total_before == 1
    payload = _last_interactive(mock_wa)
    filas = [
        (row["id"], row.get("description", ""))
        for section in payload["interactive"]["action"]["sections"]
        for row in section["rows"]
    ]
    hoy_desc = next(desc for id_, desc in filas if id_ == f"dia:{HOY.isoformat()}")
    assert hoy_desc == "horario no disponible"

    total_before = _n_calls(mock_wa)
    conv.handle_message(phone, phone, None, f"dia:{HOY.isoformat()}")
    assert _n_calls(mock_wa) - total_before == 1
    payload = _last_interactive(mock_wa)
    body = payload["interactive"]["body"]["text"].lower()
    assert "no hay servicio" not in body
    assert "no tengo el horario" in body


def test_fecha_fuera_de_vigencia_da_sin_datos(
    conv: Conv, mock_wa: MockWA, freeze_calendario: Freeze, datos_motor: Datos
) -> None:
    freeze_calendario(HOY)
    phone = "34600000104"
    conv.handle_message(phone, phone, None, "menu_horarios")
    conv.handle_message(phone, phone, "pueblo a", None)
    conv.handle_message(phone, phone, "pueblo b", None)
    conv.handle_message(phone, phone, None, "otra_fecha")
    total_before = _n_calls(mock_wa)
    conv.handle_message(phone, phone, "01/10/2027", None)
    assert _n_calls(mock_wa) - total_before == 1
    payload = _last_interactive(mock_wa)
    body = payload["interactive"]["body"]["text"].lower()
    assert "no tengo el horario" in body
    assert "no hay servicio" not in body


def test_salidas_con_linea_sin_datos_avisa(
    conv: Conv, mock_wa: MockWA, freeze_calendario: Freeze, datos_motor: Datos
) -> None:
    freeze_calendario(HOY)
    phone = "34600000105"
    conv.handle_message(phone, phone, None, "menu_horarios")
    conv.handle_message(phone, phone, "pueblo e", None)
    total_before = _n_calls(mock_wa)
    conv.handle_message(phone, phone, "pueblo f", None)
    assert _n_calls(mock_wa) - total_before == 1
    payload = _last_interactive(mock_wa)
    filas = [
        (row["id"], row.get("description", ""))
        for section in payload["interactive"]["action"]["sections"]
        for row in section["rows"]
    ]
    hoy_desc = next(desc for id_, desc in filas if id_ == f"dia:{HOY.isoformat()}")
    assert "puede haber más" in hoy_desc

    total_before = _n_calls(mock_wa)
    conv.handle_message(phone, phone, None, f"dia:{HOY.isoformat()}")
    assert _n_calls(mock_wa) - total_before == 1
    payload = _last_interactive(mock_wa)
    assert "puede haber más" in payload["interactive"]["body"]["text"].lower()


def test_a_demanda_incluye_telefono_de_la_linea(
    conv: Conv, mock_wa: MockWA, freeze_calendario: Freeze, datos_motor: Datos
) -> None:
    freeze_calendario(HOY)
    phone = "34600000106"
    conv.handle_message(phone, phone, None, "menu_horarios")
    conv.handle_message(phone, phone, "pueblo k", None)
    conv.handle_message(phone, phone, "pueblo l", None)
    total_before = _n_calls(mock_wa)
    conv.handle_message(phone, phone, None, f"dia:{HOY.isoformat()}")
    assert _n_calls(mock_wa) - total_before == 1
    payload = _last_interactive(mock_wa)
    body = payload["interactive"]["body"]["text"]
    assert "957 00 00 00" in body


def test_viernes_lectivo_solo_corre_en_viernes_de_curso(
    conv: Conv, mock_wa: MockWA, freeze_calendario: Freeze, datos_motor: Datos
) -> None:
    viernes_lectivo = date(2026, 9, 25)
    freeze_calendario(viernes_lectivo)
    phone = "34600000107"
    conv.handle_message(phone, phone, None, "menu_horarios")
    conv.handle_message(phone, phone, "pueblo a", None)
    conv.handle_message(phone, phone, "pueblo b", None)
    total_before = _n_calls(mock_wa)
    conv.handle_message(phone, phone, None, f"dia:{viernes_lectivo.isoformat()}")
    assert _n_calls(mock_wa) - total_before == 1
    payload = _last_interactive(mock_wa)
    body = payload["interactive"]["body"]["text"]
    assert "09:00" in body
    assert "Solo viernes en periodo escolar." in body

    jueves = date(2026, 9, 24)
    total_before = _n_calls(mock_wa)
    conv.handle_message(phone, phone, None, f"dia:{jueves.isoformat()}")
    assert _n_calls(mock_wa) - total_before == 1
    payload = _last_interactive(mock_wa)
    body = payload["interactive"]["body"]["text"]
    assert "09:00" not in body


def test_horas_aproximadas_sin_marca_numerica(
    conv: Conv, mock_wa: MockWA, freeze_calendario: Freeze, datos_motor: Datos
) -> None:
    freeze_calendario(HOY)
    phone = "34600000108"
    conv.handle_message(phone, phone, None, "menu_horarios")
    conv.handle_message(phone, phone, "pueblo r", None)
    conv.handle_message(phone, phone, "pueblo s", None)
    total_before = _n_calls(mock_wa)
    conv.handle_message(phone, phone, None, f"dia:{HOY.isoformat()}")
    assert _n_calls(mock_wa) - total_before == 1
    payload = _last_interactive(mock_wa)
    body = payload["interactive"]["body"]["text"]
    assert "⚠️ Horarios de paso aproximados." in body
    for marca in "¹²³⁴⁵⁶⁷⁸⁹":
        assert marca not in body


def test_otro_dia_vuelve_a_sel_dia_mismo_trayecto(
    conv: Conv, mock_wa: MockWA, freeze_calendario: Freeze
) -> None:
    freeze_calendario(HOY)
    phone = "34600000109"
    conv.handle_message(phone, phone, None, "menu_horarios")
    conv.handle_message(phone, phone, None, "loc:pozoblanco")
    conv.handle_message(phone, phone, None, "loc:cordoba")
    conv.handle_message(phone, phone, None, f"dia:{HOY.isoformat()}")
    total_before = _n_calls(mock_wa)
    conv.handle_message(phone, phone, None, "otro_dia")
    assert _n_calls(mock_wa) - total_before == 1
    payload = _last_interactive(mock_wa)
    assert payload["interactive"]["type"] == "list"
    assert "Pozoblanco → Córdoba" in payload["interactive"]["header"]["text"]


def test_ver_la_vuelta_con_trayecto_valido(
    conv: Conv, mock_wa: MockWA, freeze_calendario: Freeze
) -> None:
    freeze_calendario(HOY)
    phone = "34600000110"
    conv.handle_message(phone, phone, None, "menu_horarios")
    conv.handle_message(phone, phone, None, "loc:pozoblanco")
    conv.handle_message(phone, phone, None, "loc:cordoba")
    conv.handle_message(phone, phone, None, f"dia:{HOY.isoformat()}")
    total_before = _n_calls(mock_wa)
    conv.handle_message(phone, phone, None, "vuelta")
    assert _n_calls(mock_wa) - total_before == 1
    payload = _last_interactive(mock_wa)
    assert payload["interactive"]["type"] == "list"
    assert "Córdoba → Pozoblanco" in payload["interactive"]["header"]["text"]


def test_ver_la_vuelta_sin_trayecto(
    conv: Conv, mock_wa: MockWA, freeze_calendario: Freeze, datos_motor: Datos
) -> None:
    """Sin trayecto de vuelta, `plan_sends` mete el texto en el cuerpo del menú:
    llega un solo mensaje."""
    freeze_calendario(HOY)
    phone = "34600000111"
    conv.handle_message(phone, phone, None, "menu_horarios")
    conv.handle_message(phone, phone, "pueblo a", None)
    conv.handle_message(phone, phone, "pueblo c", None)
    conv.handle_message(phone, phone, None, f"dia:{HOY.isoformat()}")
    total_before = _n_calls(mock_wa)
    conv.handle_message(phone, phone, None, "vuelta")
    assert _n_calls(mock_wa) - total_before == 1
    body = _last_interactive(mock_wa)["interactive"]["body"]["text"]
    assert "trayecto" in body.lower()
    assert "necesitas" in body.lower()


def test_otra_consulta_muestra_lista_origen(
    conv: Conv, mock_wa: MockWA, freeze_calendario: Freeze
) -> None:
    freeze_calendario(HOY)
    phone = "34600000112"
    conv.handle_message(phone, phone, None, "menu_horarios")
    conv.handle_message(phone, phone, None, "loc:pozoblanco")
    conv.handle_message(phone, phone, None, "loc:cordoba")
    conv.handle_message(phone, phone, None, f"dia:{HOY.isoformat()}")
    total_before = _n_calls(mock_wa)
    conv.handle_message(phone, phone, None, "otra_consulta")
    assert _n_calls(mock_wa) - total_before == 1
    payload = _last_interactive(mock_wa)
    assert "pueblo" in payload["interactive"]["body"]["text"].lower()


def _rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        row for section in payload["interactive"]["action"]["sections"] for row in section["rows"]
    ]


def _assert_max_10_filas(mock_wa: MockWA) -> None:
    """Ningún mensaje interactivo enviado hasta ahora supera los límites."""
    for llamada in mock_wa["interactive"].call_args_list:
        payload = llamada[0][1]
        if payload["interactive"]["type"] == "list":
            assert len(_rows(payload)) <= 10
        else:
            assert len(payload["interactive"]["action"]["buttons"]) <= 3


def test_lineas_en_origen_pagina(conv: Conv, mock_wa: MockWA, freeze_calendario: Freeze) -> None:
    freeze_calendario(HOY)
    phone = "34600000113"
    conv.handle_message(phone, phone, None, "menu_horarios")
    conv.handle_message(phone, phone, None, "escribir")
    total_before = _n_calls(mock_wa)
    conv.handle_message(phone, phone, None, "lineas:0")
    assert _n_calls(mock_wa) - total_before == 1
    payload = _last_interactive(mock_wa)
    assert payload["interactive"]["body"]["text"] == "¿Qué línea pasa por tu pueblo?"
    ids = _row_ids(payload)
    assert len(ids) == 10  # 8 líneas + Más líneas + volver
    assert ids[0] == "linea:adamuz-cordoba:0"
    assert ids[8] == "lineas:1"
    assert ids[9] == "menu"
    assert _rows(payload)[0]["title"] == "Adamuz – Córdoba"
    assert _rows(payload)[0]["description"] == ("Adamuz – Villafranca – Córdoba · 7 pueblos")

    conv.handle_message(phone, phone, None, "lineas:1")
    ids = _row_ids(_last_interactive(mock_wa))
    assert len(ids) == 8  # 7 líneas + volver
    assert not any(r.startswith("lineas:") for r in ids)
    assert ids[-1] == "menu"
    _assert_max_10_filas(mock_wa)


def test_origen_linea_pueblo_destinos(
    conv: Conv, mock_wa: MockWA, freeze_calendario: Freeze
) -> None:
    freeze_calendario(HOY)
    phone = "34600000115"
    conv.handle_message(phone, phone, None, "menu_horarios")
    conv.handle_message(phone, phone, None, "escribir")
    conv.handle_message(phone, phone, None, "lineas:0")

    conv.handle_message(phone, phone, None, "linea:belalcazar-cordoba:0")
    payload = _last_interactive(mock_wa)
    ids = _row_ids(payload)
    assert payload["interactive"]["header"]["text"] == "🚌 Belalcázar – Córdoba"
    assert len([r for r in ids if r.startswith("loc:")]) == 8
    assert "linea:belalcazar-cordoba:1" in ids
    assert ids[-1] == "lineas:0"
    assert "loc:alcaracejos" in ids

    conv.handle_message(phone, phone, None, "linea:belalcazar-cordoba:1")
    ids = _row_ids(_last_interactive(mock_wa))
    assert len([r for r in ids if r.startswith("loc:")]) == 2
    assert "loc:cabeza-del-buey" not in ids  # va antes, alfabéticamente
    assert not any(r.startswith("linea:") for r in ids)

    conv.handle_message(phone, phone, None, "lineas:0")
    conv.handle_message(phone, phone, None, "linea:pozoblanco-cordoba:0")
    ids = _row_ids(_last_interactive(mock_wa))
    assert "loc:pozoblanco" in ids
    conv.handle_message(phone, phone, None, "loc:pozoblanco")
    payload = _last_interactive(mock_wa)
    assert "Desde Pozoblanco" in payload["interactive"]["header"]["text"]
    assert conv._get(phone).origen == "pozoblanco"
    _assert_max_10_filas(mock_wa)


def test_cabeza_del_buey_esta_en_la_linea_de_belalcazar(
    conv: Conv, mock_wa: MockWA, freeze_calendario: Freeze
) -> None:
    freeze_calendario(HOY)
    phone = "34600000118"
    conv.handle_message(phone, phone, None, "menu_horarios")
    conv.handle_message(phone, phone, None, "escribir")
    conv.handle_message(phone, phone, None, "linea:belalcazar-cordoba:0")
    filas = _rows(_last_interactive(mock_wa))
    assert "loc:cabeza-del-buey" in [f["id"] for f in filas]


def test_lineas_en_destino_solo_lineas_y_pueblos_alcanzables(
    conv: Conv, mock_wa: MockWA, freeze_calendario: Freeze
) -> None:
    freeze_calendario(HOY)
    phone = "34600000114"
    conv.handle_message(phone, phone, None, "menu_horarios")
    conv.handle_message(phone, phone, None, "loc:pozoblanco")
    conv.handle_message(phone, phone, "escribir", None)
    total_before = _n_calls(mock_wa)
    conv.handle_message(phone, phone, "lineas:0", None)
    assert _n_calls(mock_wa) - total_before == 1
    payload = _last_interactive(mock_wa)
    ids = _row_ids(payload)
    lineas = {r.split(":")[1] for r in ids if r.startswith("linea:")}
    assert lineas == {
        "belalcazar-pozoblanco",
        "cardena-pozoblanco",
        "pozoblanco-estacion-ave",
        "torrecampo-pozoblanco",
        "pozoblanco-cordoba",
        "santa-eufemia-villaralto-pozoblanco",
    }
    assert ids[-1] == "cambiar_origen"
    # "N pueblos" cuenta los alcanzables desde el origen en esa línea
    desc = {r["id"]: r["description"] for r in _rows(payload) if "description" in r}
    assert desc["linea:cardena-pozoblanco:0"] == "2 pueblos"
    assert desc["linea:belalcazar-pozoblanco:0"] == "5 pueblos"

    conv.handle_message(phone, phone, "linea:pozoblanco-cordoba:0", None)
    ids = _row_ids(_last_interactive(mock_wa))
    pueblos = {r for r in ids if r.startswith("loc:")}
    assert "loc:pozoblanco" not in pueblos
    assert pueblos == {
        "loc:alcaracejos",
        "loc:conquista",
        "loc:cordoba",
        "loc:cruce-de-villaharta",
        "loc:villaharta",
        "loc:villanueva-de-cordoba",
    }
    conv.handle_message(phone, phone, "loc:cordoba", None)
    assert any(r.startswith("dia:") for r in _row_ids(_last_interactive(mock_wa)))
    _assert_max_10_filas(mock_wa)


def test_lineas_en_destino_volver_es_cambiar_origen(
    conv: Conv, mock_wa: MockWA, freeze_calendario: Freeze
) -> None:
    freeze_calendario(HOY)
    phone = "34600000119"
    conv.handle_message(phone, phone, None, "menu_horarios")
    conv.handle_message(phone, phone, None, "loc:pozoblanco")
    conv.handle_message(phone, phone, "escribir", None)
    conv.handle_message(phone, phone, "lineas:0", None)
    conv.handle_message(phone, phone, None, "cambiar_origen")
    payload = _last_interactive(mock_wa)
    assert "pueblo" in payload["interactive"]["body"]["text"].lower()
    assert "loc:pozoblanco" in _row_ids(payload)
    assert conv._get(phone).step == conv.flujo.SEL_ORIGEN
    assert conv._get(phone).origen is None


def test_lineas_en_destino_volver_a_lineas_desde_una_linea(
    conv: Conv, mock_wa: MockWA, freeze_calendario: Freeze
) -> None:
    freeze_calendario(HOY)
    phone = "34600000120"
    conv.handle_message(phone, phone, None, "menu_horarios")
    conv.handle_message(phone, phone, None, "loc:pozoblanco")
    conv.handle_message(phone, phone, "lineas:0", None)
    conv.handle_message(phone, phone, "linea:torrecampo-pozoblanco:0", None)
    assert _row_ids(_last_interactive(mock_wa))[-1] == "lineas:0"
    conv.handle_message(phone, phone, "lineas:0", None)
    assert _row_ids(_last_interactive(mock_wa))[-1] == "cambiar_origen"


@pytest.mark.parametrize(
    "valor",
    [
        "linea:no-existe:0",
        "linea:adamuz-cordoba:99",
        "linea:adamuz-cordoba:-1",
        "linea:x",
        "linea:x:abc",
        "linea:x:-1",
        "linea:adamuz-cordoba:abc",
        "linea:a:b:c",
        "linea:",
        "lineas:zz",
        "lineas:99",
        "lineas:-3",
        "lineas:",
        "zonas",
        "zona:extremadura:0",
        "zona:x",
    ],
)
def test_ids_malformados_o_antiguos_muestran_la_lista_de_lineas(
    conv: Conv, mock_wa: MockWA, freeze_calendario: Freeze, valor: str
) -> None:
    freeze_calendario(HOY)
    phone = "34600000121"
    conv.handle_message(phone, phone, None, "menu_horarios")
    conv.handle_message(phone, phone, None, "escribir")
    total_before = _n_calls(mock_wa)
    conv.handle_message(phone, phone, None, valor)
    assert _n_calls(mock_wa) - total_before == 1
    payload = _last_interactive(mock_wa)
    assert payload["interactive"]["body"]["text"] == "¿Qué línea pasa por tu pueblo?"
    assert _row_ids(payload)[0] == "linea:adamuz-cordoba:0"
    assert "No conozco ese pueblo" not in payload["interactive"]["body"]["text"]
    _assert_max_10_filas(mock_wa)


@pytest.mark.parametrize(
    "valor",
    [
        "linea:adamuz-cordoba:0",  # existe, pero no sale de Pozoblanco
        "linea:no-existe:0",
        "linea:x:abc",
        "linea:pozoblanco-cordoba:-1",
        "linea:pozoblanco-cordoba:99",
        "lineas:zz",
        "zonas",
        "zona:los-pedroches:0",
    ],
)
def test_ids_malformados_en_destino_muestran_la_lista_de_lineas(
    conv: Conv, mock_wa: MockWA, freeze_calendario: Freeze, valor: str
) -> None:
    freeze_calendario(HOY)
    phone = "34600000122"
    conv.handle_message(phone, phone, None, "menu_horarios")
    conv.handle_message(phone, phone, None, "loc:pozoblanco")
    conv.handle_message(phone, phone, None, valor)
    payload = _last_interactive(mock_wa)
    assert payload["interactive"]["body"]["text"] == "¿Qué línea pasa por tu pueblo?"
    ids = _row_ids(payload)
    assert "linea:adamuz-cordoba:0" not in ids
    assert ids[-1] == "cambiar_origen"


def test_sin_coincidencia_ofrece_ver_pueblos_por_linea(
    conv: Conv, mock_wa: MockWA, freeze_calendario: Freeze
) -> None:
    freeze_calendario(HOY)
    phone = "34600000123"
    conv.handle_message(phone, phone, None, "menu_horarios")
    conv.handle_message(phone, phone, "xyzxyz", None)
    payload = _last_interactive(mock_wa)
    assert "No conozco ese pueblo" in payload["interactive"]["body"]["text"]
    assert {"id": "lineas:0", "title": "🚌 Ver pueblos por línea"} in _rows(payload)
    conv.handle_message(phone, phone, None, "lineas:0")
    assert _row_ids(_last_interactive(mock_wa))[0] == "linea:adamuz-cordoba:0"


def test_sin_coincidencia_en_destino_ofrece_ver_pueblos_por_linea(
    conv: Conv, mock_wa: MockWA, freeze_calendario: Freeze
) -> None:
    freeze_calendario(HOY)
    phone = "34600000124"
    conv.handle_message(phone, phone, None, "menu_horarios")
    conv.handle_message(phone, phone, None, "loc:pozoblanco")
    conv.handle_message(phone, phone, "xyzxyz", None)
    payload = _last_interactive(mock_wa)
    assert "No conozco ese pueblo" in payload["interactive"]["body"]["text"]
    assert "lineas:0" in _row_ids(payload)
    _assert_max_10_filas(mock_wa)


def test_escribir_ofrece_boton_ver_por_linea(
    conv: Conv, mock_wa: MockWA, freeze_calendario: Freeze
) -> None:
    freeze_calendario(HOY)
    phone = "34600000125"
    conv.handle_message(phone, phone, None, "menu_horarios")
    conv.handle_message(phone, phone, None, "escribir")
    botones = _last_interactive(mock_wa)["interactive"]["action"]["buttons"]
    assert botones[0]["reply"] == {"id": "lineas:0", "title": "🚌 Ver por línea"}
    conv.handle_message(phone, phone, None, "loc:pozoblanco")
    conv.handle_message(phone, phone, "escribir", None)
    botones = _last_interactive(mock_wa)["interactive"]["action"]["buttons"]
    assert botones[0]["reply"]["id"] == "lineas:0"
    assert botones[1]["reply"]["id"] == "cambiar_origen"


def test_lineas_con_muchas_lineas_paginan_y_no_pasan_de_10_filas(
    conv: Conv, mock_wa: MockWA, freeze_calendario: Freeze, datos_muchas_lineas: Datos
) -> None:
    freeze_calendario(HOY)
    phone = "34600000126"
    conv.handle_message(phone, phone, None, "menu_horarios")
    conv.handle_message(phone, phone, None, "escribir")
    conv.handle_message(phone, phone, None, "lineas:0")
    ids = _row_ids(_last_interactive(mock_wa))
    assert len(ids) == 10 and ids[8] == "lineas:1"
    conv.handle_message(phone, phone, None, "lineas:1")
    payload = _last_interactive(mock_wa)
    ids = _row_ids(payload)
    assert ids[-2:] == ["linea:ruta-norte:0", "menu"]
    fila_ruta = _rows(payload)[-2]
    assert fila_ruta["title"] == "Ruta del norte"
    assert fila_ruta["description"] == ("Ruta muy larga del norte al sur de la sierra · 3 pueblos")
    # la línea de 19 pueblos: 3 páginas
    conv.handle_message(phone, phone, None, "linea:linea-larga:0")
    ids = _row_ids(_last_interactive(mock_wa))
    assert "linea:linea-larga:1" in ids
    conv.handle_message(phone, phone, None, "linea:linea-larga:1")
    ids = _row_ids(_last_interactive(mock_wa))
    assert "linea:linea-larga:2" in ids
    conv.handle_message(phone, phone, None, "linea:linea-larga:2")
    ids = _row_ids(_last_interactive(mock_wa))
    assert len([r for r in ids if r.startswith("loc:")]) == 3
    assert not any(r.startswith("linea:") for r in ids)
    _assert_max_10_filas(mock_wa)


def test_destino_con_muchas_lineas_solo_las_del_origen(
    conv: Conv, mock_wa: MockWA, freeze_calendario: Freeze, datos_muchas_lineas: Datos
) -> None:
    freeze_calendario(HOY)
    phone = "34600000127"
    conv.handle_message(phone, phone, None, "menu_horarios")
    conv.handle_message(phone, phone, None, "loc:origen")
    payload = _last_interactive(mock_wa)
    assert "escribir" in _row_ids(payload)  # 29 destinos: no caben en la lista
    _assert_max_10_filas(mock_wa)
    conv.handle_message(phone, phone, None, "escribir")
    conv.handle_message(phone, phone, None, "lineas:0")
    ids = _row_ids(_last_interactive(mock_wa))
    assert len(ids) == 10 and ids[8] == "lineas:1"
    conv.handle_message(phone, phone, None, "linea:linea-larga:0")
    ids = _row_ids(_last_interactive(mock_wa))
    assert "loc:origen" not in ids
    _assert_max_10_filas(mock_wa)


def test_aldea_pendiente_no_sale_en_ninguna_linea(
    conv: Conv, mock_wa: MockWA, freeze_calendario: Freeze, datos_pendientes: Datos
) -> None:
    freeze_calendario(HOY)
    phone = "34600000128"
    conv.handle_message(phone, phone, None, "menu_horarios")
    conv.handle_message(phone, phone, None, "escribir")
    conv.handle_message(phone, phone, None, "lineas:0")
    payload = _last_interactive(mock_wa)
    linea_ids = [r for r in _row_ids(payload) if r.startswith("linea:")]
    assert linea_ids
    for fila in linea_ids:
        conv.handle_message(phone, phone, None, fila)
        assert "loc:aldea-a" not in _row_ids(_last_interactive(mock_wa))
        assert "loc:aldea-b" not in _row_ids(_last_interactive(mock_wa))


def test_demasiadas_coincidencias_pide_mas_concreto(
    conv: Conv, mock_wa: MockWA, freeze_calendario: Freeze, monkeypatch: pytest.MonkeyPatch
) -> None:
    freeze_calendario(HOY)
    phone = "34600000115"
    conv.handle_message(phone, phone, None, "menu_horarios")
    monkeypatch.setattr(
        conv.instalados["datos"].matcher,
        "buscar",
        lambda texto: Coincidencia(tipo="demasiadas", localidades=(), texto_normalizado="a"),
    )
    total_before = _n_calls(mock_wa)
    conv.handle_message(phone, phone, "a", None)
    assert _n_calls(mock_wa) - total_before == 1
    payload = _last_interactive(mock_wa)
    body = payload["interactive"]["body"]["text"].lower()
    assert "concreto" in body


def test_no_tras_confirmar_pide_escribirlo_de_otra_forma(
    conv: Conv, mock_wa: MockWA, freeze_calendario: Freeze
) -> None:
    freeze_calendario(HOY)
    phone = "34600000116"
    conv.handle_message(phone, phone, None, "menu_horarios")
    conv.handle_message(phone, phone, "pozoblnco", None)
    total_before = _n_calls(mock_wa)
    conv.handle_message(phone, phone, None, "no")
    assert _n_calls(mock_wa) - total_before == 1
    payload = _last_interactive(mock_wa)
    assert payload["interactive"]["type"] == "button"
    body = payload["interactive"]["body"]["text"].lower()
    assert "otra forma" in body
    botones = payload["interactive"]["action"]["buttons"]
    assert any(b["reply"]["id"] == "lineas:0" for b in botones)
    assert conv._get(phone).step == conv.flujo.ESCRIBIR_ORIGEN


def test_fecha_escrita_directamente_en_lista_de_dias(
    conv: Conv, mock_wa: MockWA, freeze_calendario: Freeze
) -> None:
    freeze_calendario(HOY)
    phone = "34600000117"
    conv.handle_message(phone, phone, None, "menu_horarios")
    conv.handle_message(phone, phone, None, "loc:pozoblanco")
    conv.handle_message(phone, phone, None, "loc:cordoba")
    total_before = _n_calls(mock_wa)
    conv.handle_message(phone, phone, "25/12", None)
    assert _n_calls(mock_wa) - total_before == 1
    payload = _last_interactive(mock_wa)
    assert payload["interactive"]["type"] == "button"


def test_texto_no_valido_en_lista_de_dias_un_solo_mensaje(
    conv: Conv, mock_wa: MockWA, freeze_calendario: Freeze
) -> None:
    freeze_calendario(HOY)
    phone = "34600000118"
    conv.handle_message(phone, phone, None, "menu_horarios")
    conv.handle_message(phone, phone, None, "loc:pozoblanco")
    conv.handle_message(phone, phone, None, "loc:cordoba")
    total_before = _n_calls(mock_wa)
    conv.handle_message(phone, phone, "mañana", None)
    assert _n_calls(mock_wa) - total_before == 1
    payload = _last_interactive(mock_wa)
    assert payload["interactive"]["type"] == "list"
    assert "lista" in payload["interactive"]["body"]["text"].lower()


def test_fecha_pasada_en_lista_de_dias_un_solo_mensaje(
    conv: Conv, mock_wa: MockWA, freeze_calendario: Freeze
) -> None:
    freeze_calendario(HOY)
    phone = "34600000119"
    conv.handle_message(phone, phone, None, "menu_horarios")
    conv.handle_message(phone, phone, None, "loc:pozoblanco")
    conv.handle_message(phone, phone, None, "loc:cordoba")
    total_before = _n_calls(mock_wa)
    conv.handle_message(phone, phone, "20/09", None)
    assert _n_calls(mock_wa) - total_before == 1
    payload = _last_interactive(mock_wa)
    assert "pasado" in payload["interactive"]["body"]["text"].lower()


def test_fecha_pasada_en_escribir_fecha_un_solo_mensaje(
    conv: Conv, mock_wa: MockWA, freeze_calendario: Freeze
) -> None:
    freeze_calendario(HOY)
    phone = "34600000120"
    conv.handle_message(phone, phone, None, "menu_horarios")
    conv.handle_message(phone, phone, None, "loc:pozoblanco")
    conv.handle_message(phone, phone, None, "loc:cordoba")
    conv.handle_message(phone, phone, None, "otra_fecha")
    total_before = _n_calls(mock_wa)
    conv.handle_message(phone, phone, "20/09", None)
    assert _n_calls(mock_wa) - total_before == 1
    text = _last_text(mock_wa)
    assert "pasado" in text.lower()
    assert "25/12" in text  # formato de ejemplo, en el mismo mensaje


def test_origen_con_mas_de_9_destinos_muestra_10_filas(
    conv: Conv, mock_wa: MockWA, freeze_calendario: Freeze
) -> None:
    freeze_calendario(HOY)
    phone = "34600000121"
    conv.handle_message(phone, phone, None, "menu_horarios")
    total_before = _n_calls(mock_wa)
    conv.handle_message(phone, phone, None, "loc:cordoba")
    assert _n_calls(mock_wa) - total_before == 1
    payload = _last_interactive(mock_wa)
    filas = [
        row for section in payload["interactive"]["action"]["sections"] for row in section["rows"]
    ]
    assert len(filas) == 10
    assert any("Otro destino" in row["title"] for row in filas)


def test_log_redaction_numero_telefono(
    conv: Conv, mock_wa: MockWA, freeze_calendario: Freeze, caplog: pytest.LogCaptureFixture
) -> None:
    import logging

    freeze_calendario(HOY)
    phone = "34600000122"
    conv.handle_message(phone, phone, None, "menu_horarios")
    conv.handle_message(phone, phone, None, "loc:pozoblanco")
    conv.handle_message(phone, phone, None, "loc:cordoba")
    conv.handle_message(phone, phone, None, "otra_fecha")
    caplog.set_level(logging.INFO, logger="packs.bus")
    numero = "612345678"
    total_before = _n_calls(mock_wa)
    conv.handle_message(phone, phone, numero, None)
    assert _n_calls(mock_wa) - total_before == 1
    encontrado = False
    for r in caplog.records:
        if "[NO_RECONOCIDO]" in r.message:
            encontrado = True
            assert numero not in r.message
            assert "<numero>" in r.message
    assert encontrado


def test_log_redaction_numero_telefono_con_separadores(
    conv: Conv, mock_wa: MockWA, freeze_calendario: Freeze, caplog: pytest.LogCaptureFixture
) -> None:
    """`formato.normalizar()` sustituye separadores por espacios, así que un
    número escrito con espacios o guiones no debe colar como si tuviera menos
    de 6 dígitos consecutivos."""
    import logging

    freeze_calendario(HOY)
    phone = "34600000124"
    conv.handle_message(phone, phone, None, "menu_horarios")
    conv.handle_message(phone, phone, None, "loc:pozoblanco")
    conv.handle_message(phone, phone, None, "loc:cordoba")
    conv.handle_message(phone, phone, None, "otra_fecha")
    caplog.set_level(logging.INFO, logger="packs.bus")
    numero = "612 34 56 78"
    total_before = _n_calls(mock_wa)
    conv.handle_message(phone, phone, numero, None)
    assert _n_calls(mock_wa) - total_before == 1
    encontrado = False
    for r in caplog.records:
        assert numero not in r.message
        if "[NO_RECONOCIDO]" in r.message:
            encontrado = True
            assert "<numero>" in r.message
    assert encontrado


def test_status_no_es_un_comando_del_pack(
    conv: Conv, mock_wa: MockWA, freeze_calendario: Freeze
) -> None:
    # Comandos como `/status` o `/logs` son de la plataforma; para el pack son
    # texto normal.
    freeze_calendario(HOY)
    otro_phone = "34600000123"
    total_before = _n_calls(mock_wa)
    conv.handle_message(otro_phone, otro_phone, "/status", None)
    assert _n_calls(mock_wa) - total_before == 1
    payload = _last_interactive(mock_wa)
    # no es un comando de administrador: se trata como texto normal, vuelve
    # al menú (id/texto desconocido)
    assert "necesitas" in payload["interactive"]["body"]["text"].lower()


# ── Sin servicio en ninguna línea (P03g) ────────────────────────────────────


def test_lista_de_dias_muestra_sin_servicio_el_25_12(
    conv: Conv, mock_wa: MockWA, freeze_calendario: Freeze
) -> None:
    freeze_calendario(date(2026, 12, 22))
    phone = "34600000201"
    conv.handle_message(phone, phone, None, "menu_horarios")
    conv.handle_message(phone, phone, None, "loc:pozoblanco")
    conv.handle_message(phone, phone, None, "loc:cordoba")
    payload = _last_interactive(mock_wa)
    filas = {
        row["id"]: row
        for section in payload["interactive"]["action"]["sections"]
        for row in section["rows"]
    }
    fila = filas["dia:2026-12-25"]
    assert fila["description"] == "festivo · sin servicio"
    assert len(fila["description"]) <= 72


def test_resultado_25_12_sin_servicio_en_ninguna_linea(
    conv: Conv, mock_wa: MockWA, freeze_calendario: Freeze
) -> None:
    freeze_calendario(date(2026, 12, 22))
    phone = "34600000202"
    conv.handle_message(phone, phone, None, "menu_horarios")
    conv.handle_message(phone, phone, None, "loc:pozoblanco")
    conv.handle_message(phone, phone, None, "loc:cordoba")
    conv.handle_message(phone, phone, None, "dia:2026-12-25")
    payload = _last_interactive(mock_wa)
    body = payload["interactive"]["body"]["text"]
    assert "festivo (Navidad)" in body
    assert "El 25/12 no hay servicio en ninguna línea" in body
    assert NEGOCIO_TELEFONO in body
    assert "sábado 26/12" in body
    assert "dia:2026-12-26" in _button_ids(payload)
    assert "No hay salidas en los próximos días" not in body


# ── Festivos locales (P03e) ────────────────────────────────────────────────


def test_festivo_local_de_cordoba_en_lista_y_resultado(
    conv: Conv, mock_wa: MockWA, freeze_calendario: Freeze
) -> None:
    freeze_calendario(date(2026, 10, 20))
    phone = "34600000203"
    conv.handle_message(phone, phone, None, "menu_horarios")
    conv.handle_message(phone, phone, None, "loc:pozoblanco")
    conv.handle_message(phone, phone, None, "loc:cordoba")
    payload = _last_interactive(mock_wa)
    filas = {
        row["id"]: row
        for section in payload["interactive"]["action"]["sections"]
        for row in section["rows"]
    }
    descripcion = filas["dia:2026-10-24"]["description"]
    assert descripcion.startswith("festivo · ")
    assert len(descripcion) <= 72
    assert not filas["dia:2026-10-23"]["description"].startswith("festivo")

    conv.handle_message(phone, phone, None, "dia:2026-10-24")
    body = _last_interactive(mock_wa)["interactive"]["body"]["text"]
    assert "festivo en Córdoba (San Rafael)" in body
    assert "17:45" in body


# ── Trayectos no vendibles (P12b) ──────────────────────────────────────────


def test_destino_escrito_no_vendible_da_mensaje_propio(
    conv: Conv, mock_wa: MockWA, freeze_calendario: Freeze
) -> None:
    freeze_calendario(HOY)
    phone = "34600000204"
    conv.handle_message(phone, phone, None, "menu_horarios")
    conv.handle_message(phone, phone, None, "loc:cordoba")
    conv.handle_message(phone, phone, "Alcolea", None)
    payload = _last_interactive(mock_wa)
    body = payload["interactive"]["body"]["text"]
    assert "no vendemos billetes" in body
    assert "Córdoba" in body and "Alcolea" in body
    assert "No hay trayecto directo" not in body
    assert conv._get(phone).step == conv.flujo.SEL_DESTINO
    # y Alcolea no aparece como destino ofrecido
    assert "loc:alcolea" not in _row_ids(payload)


def test_destino_escrito_sin_trayecto_sigue_dando_sin_trayecto(
    conv: Conv, mock_wa: MockWA, freeze_calendario: Freeze
) -> None:
    freeze_calendario(HOY)
    phone = "34600000205"
    conv.handle_message(phone, phone, None, "menu_horarios")
    conv.handle_message(phone, phone, None, "loc:pozoblanco")
    conv.handle_message(phone, phone, "badajoz", None)
    body = _last_interactive(mock_wa)["interactive"]["body"]["text"]
    assert "No hay trayecto directo" in body
    assert "no vendemos" not in body


def test_cambio_de_origen_a_par_no_vendible_da_mensaje_propio(
    conv: Conv, mock_wa: MockWA, freeze_calendario: Freeze
) -> None:
    # Rama defensiva de "ver la vuelta": se fuerza un estado cuyo par
    # invertido (alcolea -> campus-de-rabanales) es no vendible.
    freeze_calendario(HOY)
    phone = "34600000206"
    conv.handle_message(phone, phone, None, "menu_horarios")
    conv.handle_message(phone, phone, None, "loc:cordoba")
    conv.handle_message(phone, phone, None, "loc:pozoblanco")
    conv.handle_message(phone, phone, None, f"dia:{HOY.isoformat()}")
    conv.forzar(phone, origen="campus-de-rabanales", destino="alcolea")
    conv.handle_message(phone, phone, None, "vuelta")
    # El aviso llega dentro del cuerpo del menú (`plan_sends`).
    text = _last_interactive(mock_wa)["interactive"]["body"]["text"]
    assert "no vendemos billetes" in text
    assert "No hay trayecto directo" not in text


# ── Localidades pendientes (ciclo C2, P15/P32) ───────────────────────────────


def _all_texts(mock_wa: MockWA) -> list[str]:
    """Texto de cuerpo de todo lo enviado (interactivos y texto plano)."""
    textos = [c[0][1] for c in mock_wa["text"].call_args_list]
    for c in mock_wa["interactive"].call_args_list:
        textos.append(c[0][1]["interactive"]["body"]["text"])
    return textos


def _no_hay_sin_trayecto(mock_wa: MockWA) -> None:
    assert not any("directo" in t and "Aldea" in t for t in _all_texts(mock_wa))
    assert not any("No hay autobuses" in t for t in _all_texts(mock_wa))


def _pend_menu(conv: Conv, phone: str) -> None:
    conv.handle_message(phone, phone, None, "menu_horarios")


def test_pendiente_en_origen_ofrece_usar_ver(
    conv: Conv, mock_wa: MockWA, freeze_calendario: Freeze, datos_pendientes: Datos
) -> None:
    freeze_calendario(HOY)
    phone = "34600000101"
    _pend_menu(conv, phone)
    conv.handle_message(phone, phone, "Aldea A", None)
    payload = _last_interactive(mock_wa)
    assert payload["interactive"]["body"]["text"] == (
        "Algunos autobuses paran en Aldea A, a unos 4 minutos de Pueblo A, pero "
        "aún no tenemos su hora de paso."
    )
    assert _button_ids(payload) == ["usar:pueblo-a", "escribir"]
    assert conv._states[phone].origen is None

    conv.handle_message(phone, phone, None, "usar:pueblo-a")
    payload = _last_interactive(mock_wa)
    assert "Desde Pueblo A" in payload["interactive"]["header"]["text"]
    assert set(_row_ids(payload)) >= {"loc:pueblo-b", "loc:pueblo-c"}
    assert "loc:aldea-a" not in _row_ids(payload)
    _no_hay_sin_trayecto(mock_wa)


def test_pendiente_en_destino_ofrece_usar_ver(
    conv: Conv, mock_wa: MockWA, freeze_calendario: Freeze, datos_pendientes: Datos
) -> None:
    freeze_calendario(HOY)
    phone = "34600000102"
    _pend_menu(conv, phone)
    conv.handle_message(phone, phone, None, "loc:pueblo-a")
    conv.handle_message(phone, phone, "Aldea Bonita", None)
    payload = _last_interactive(mock_wa)
    assert "a unos 7 minutos de Pueblo B" in payload["interactive"]["body"]["text"]
    assert _button_ids(payload) == ["usar:pueblo-b", "escribir"]
    assert conv._states[phone].origen == "pueblo-a"

    conv.handle_message(phone, phone, None, "usar:pueblo-b")
    payload = _last_interactive(mock_wa)
    assert "Pueblo A → Pueblo B" in payload["interactive"]["header"]["text"]
    assert any(r.startswith("dia:") for r in _row_ids(payload))
    _no_hay_sin_trayecto(mock_wa)


def test_pendiente_otro_pueblo_repregunta(
    conv: Conv, mock_wa: MockWA, freeze_calendario: Freeze, datos_pendientes: Datos
) -> None:
    freeze_calendario(HOY)
    phone = "34600000103"
    _pend_menu(conv, phone)
    conv.handle_message(phone, phone, "Aldea A", None)
    conv.handle_message(phone, phone, None, "escribir")
    payload = _last_interactive(mock_wa)
    assert "pueblo" in payload["interactive"]["body"]["text"].lower()
    assert conv._states[phone].step == "ESCRIBIR_ORIGEN"
    conv.handle_message(phone, phone, "Pueblo B", None)
    payload = _last_interactive(mock_wa)
    assert "Desde Pueblo B" in payload["interactive"]["header"]["text"]


def test_pendiente_desde_lista_de_candidatas(
    conv: Conv, mock_wa: MockWA, freeze_calendario: Freeze, datos_pendientes: Datos
) -> None:
    freeze_calendario(HOY)
    phone = "34600000104"
    _pend_menu(conv, phone)
    conv.handle_message(phone, phone, "aldea", None)
    payload = _last_interactive(mock_wa)
    assert _button_ids(payload) == ["loc:aldea-a", "loc:aldea-b"]
    conv.handle_message(phone, phone, None, "loc:aldea-b")
    payload = _last_interactive(mock_wa)
    assert _button_ids(payload) == ["usar:pueblo-b", "escribir"]
    _no_hay_sin_trayecto(mock_wa)


def test_pendiente_desde_errata_confirmada(
    conv: Conv, mock_wa: MockWA, freeze_calendario: Freeze, datos_pendientes: Datos
) -> None:
    freeze_calendario(HOY)
    phone = "34600000105"
    _pend_menu(conv, phone)
    conv.handle_message(phone, phone, "aldeaa", None)
    assert _button_ids(_last_interactive(mock_wa)) == ["si", "no"]
    conv.handle_message(phone, phone, None, "si")
    payload = _last_interactive(mock_wa)
    assert _button_ids(payload) == ["usar:pueblo-a", "escribir"]
    assert conv._states[phone].step == "SEL_ORIGEN"
    _no_hay_sin_trayecto(mock_wa)


def test_pendiente_cuyo_ver_es_el_origen(
    conv: Conv, mock_wa: MockWA, freeze_calendario: Freeze, datos_pendientes: Datos
) -> None:
    freeze_calendario(HOY)
    phone = "34600000106"
    _pend_menu(conv, phone)
    conv.handle_message(phone, phone, None, "loc:pueblo-a")
    conv.handle_message(phone, phone, "Aldea A", None)
    assert _button_ids(_last_interactive(mock_wa)) == ["usar:pueblo-a", "escribir"]
    conv.handle_message(phone, phone, None, "usar:pueblo-a")
    payload = _last_interactive(mock_wa)
    assert "Elige un destino distinto" in payload["interactive"]["body"]["text"]
    assert conv._states[phone].step == "SEL_DESTINO"


@pytest.mark.parametrize("valor", ["usar:no-existe", "usar:aldea-a"])
def test_usar_manipulado_repite_el_paso(
    conv: Conv, mock_wa: MockWA, freeze_calendario: Freeze, datos_pendientes: Datos, valor: str
) -> None:
    freeze_calendario(HOY)
    phone = "34600000107"
    _pend_menu(conv, phone)
    conv.handle_message(phone, phone, None, valor)
    payload = _last_interactive(mock_wa)
    assert "loc:pueblo-a" in _row_ids(payload)
    assert conv._states[phone].step == "SEL_ORIGEN"
    assert conv._states[phone].origen is None

    conv.handle_message(phone, phone, None, "loc:pueblo-a")
    conv.handle_message(phone, phone, None, valor)
    payload = _last_interactive(mock_wa)
    assert "Desde Pueblo A" in payload["interactive"]["header"]["text"]
    assert conv._states[phone].step == "SEL_DESTINO"
    assert conv._states[phone].origen == "pueblo-a"
    _no_hay_sin_trayecto(mock_wa)


# ── Los Mochos y Rivero de Posadas con los datos reales (P32 cerrada) ─────────


def test_real_los_mochos_como_origen_es_un_pueblo_normal(
    conv: Conv, mock_wa: MockWA, freeze_calendario: Freeze
) -> None:
    freeze_calendario(HOY)
    phone = "34600000121"
    conv.handle_message(phone, phone, None, "menu_horarios")
    conv.handle_message(phone, phone, "Los Mochos", None)
    payload = _last_interactive(mock_wa)
    assert "Desde Los Mochos" in payload["interactive"]["header"]["text"]
    assert conv._states[phone].step == "SEL_DESTINO"
    assert conv._states[phone].origen == "los-mochos"


def test_real_los_mochos_como_destino_llega_al_resultado(
    conv: Conv, mock_wa: MockWA, freeze_calendario: Freeze
) -> None:
    freeze_calendario(HOY)
    phone = "34600000122"
    conv.handle_message(phone, phone, None, "menu_horarios")
    conv.handle_message(phone, phone, None, "loc:cordoba")
    conv.handle_message(phone, phone, "Los Mochos", None)
    payload = _last_interactive(mock_wa)
    assert "Córdoba → Los Mochos" in payload["interactive"]["header"]["text"]
    assert conv._states[phone].step == "SEL_DIA"
    assert conv._states[phone].destino == "los-mochos"

    total_before = _n_calls(mock_wa)
    conv.handle_message(phone, phone, None, f"dia:{HOY.isoformat()}")
    assert _n_calls(mock_wa) - total_before == 1
    body = _last_interactive(mock_wa)["interactive"]["body"]["text"]
    assert "Los Mochos" in body
    # La nota común a todas las salidas sale una sola vez en la respuesta.
    assert body.count("Horarios de paso aproximados.") == 1
