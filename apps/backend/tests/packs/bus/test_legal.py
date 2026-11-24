"""Escenarios legales del pack `bus`: aviso inicial (RGPD art. 13), PERSONA y BAJA ya
retiradas (ADR-028) y aviso de horarios orientativos. El texto del aviso inicial es de la
plataforma (`core.conversation`); aquí se comprueba con el pack, en los dos canales."""

from __future__ import annotations

import pytest

from core.testing.harness import ChannelType, Conversation
from packs.bus.config import DEFAULT_DISCLAIMER, BusConfig
from packs.bus.pack import pack
from tests.packs.bus.demo import CONFIG, datos_demo
from tests.packs.bus.test_escenarios import MENU, MIERCOLES, charla, cuerpo, hasta_dias


@pytest.fixture(params=["whatsapp", "telegram"])
def canal(request: pytest.FixtureRequest) -> ChannelType:
    return request.param  # type: ignore[no-any-return]


AVISO = "Horarios orientativos; confirma con la compañía."


LINEA = "_🤖 Asistente automático de Negocio de prueba_"


def test_el_aviso_va_debajo_del_menu_cada_vez(canal: ChannelType) -> None:
    chat = charla(canal)
    # Una sola burbuja: el menú y, como última línea, el aviso.
    (menu,) = chat.send("hola").expect(buttons=MENU).replies
    assert menu.body == f"¿Qué necesitas?\n\n{LINEA}"
    # Fuera del menú no sale…
    origen = chat.press("menu_horarios")
    assert all("Asistente automático" not in r.body for r in origen.replies)
    # …y al volver al menú, por botón o por palabra, sale otra vez.
    assert chat.press("menu").replies[-1].body.endswith(LINEA)
    assert chat.send("hola").replies[-1].body.endswith(LINEA)


def test_el_aviso_no_sale_en_los_resultados(canal: ChannelType) -> None:
    chat = charla(canal)
    hasta_dias(chat)
    assert "Asistente automático" not in cuerpo(chat.press("dia:2026-09-24"))


@pytest.mark.parametrize("palabra", ["persona", "baja", "stop", "alta"])
def test_persona_y_baja_ya_no_son_ordenes(canal: ChannelType, palabra: str) -> None:
    """ADR-028: se buscan como cualquier pueblo escrito, sin aviso al dueño."""
    chat = charla(canal)
    chat.send("hola")
    chat.press("menu_horarios")
    chat.send(palabra).expect(text_contains="No conozco ese pueblo")
    assert chat.state["step"] == "SEL_ORIGEN"
    assert chat.notifications == [] and not chat.contact.opt_out


def test_el_resultado_lleva_el_aviso_de_horarios_orientativos(canal: ChannelType) -> None:
    chat = charla(canal)
    hasta_dias(chat)
    texto = cuerpo(chat.press("dia:2026-09-24"))
    assert texto.endswith(f"\n\n{AVISO}")
    assert DEFAULT_DISCLAIMER == AVISO


def test_el_aviso_tambien_va_en_dias_sin_servicio(canal: ChannelType) -> None:
    chat = charla(canal)
    hasta_dias(chat)
    assert AVISO in cuerpo(chat.press("dia:2026-09-26"))  # sábado: sin servicio


def test_el_aviso_es_configurable_y_se_puede_quitar() -> None:
    base = CONFIG.model_dump(mode="json")
    propio = BusConfig.model_validate({**base, "schedule_disclaimer": "Consulta en taquilla."})
    chat = _charla(propio)
    hasta_dias(chat)
    texto = cuerpo(chat.press("dia:2026-09-24"))
    assert texto.endswith("\n\nConsulta en taquilla.") and AVISO not in texto
    vacio = BusConfig.model_validate({**base, "schedule_disclaimer": ""})
    chat = _charla(vacio)
    hasta_dias(chat)
    assert "orientativos" not in cuerpo(chat.press("dia:2026-09-24"))


def _charla(config: BusConfig) -> Conversation:
    return Conversation(pack, config=config, data=datos_demo(), channel="whatsapp", now=MIERCOLES)
