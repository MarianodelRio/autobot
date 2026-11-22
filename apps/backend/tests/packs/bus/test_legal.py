"""Escenarios legales del pack `bus`: aviso inicial, PERSONA, STOP y aviso de horarios
orientativos (RGPD art. 13, Ley 10/2025). El texto del aviso, de PERSONA y de la baja es
de la plataforma (`core.conversation`); aquí se comprueban con el pack, en los dos canales."""

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


def test_el_aviso_inicial_va_una_sola_vez(canal: ChannelType) -> None:
    chat = charla(canal)
    primero = chat.send("hola").expect(buttons=MENU)
    # El aviso y el menú caben en un solo mensaje (`plan_sends` los une).
    assert len(primero.replies) == 1
    assert "asistente automático de Negocio de prueba" in primero.replies[0].body
    assert "asistente automático" not in chat.send("hola").replies[0].body


def test_persona_en_cualquier_paso(canal: ChannelType) -> None:
    chat = charla(canal)
    hasta_dias(chat)
    paso = chat.state["step"]
    chat.send("persona").expect(text_contains="contacta directamente con Negocio de prueba")
    assert chat.state["step"] == paso
    assert [n.kind for n in chat.notifications] == ["human_requested"]


def test_stop_y_baja(canal: ChannelType) -> None:
    chat = charla(canal)
    chat.send("hola")
    chat.send("STOP").expect(text_contains="borren tus datos")
    assert chat.contact.opt_out
    chat.send("alta")
    assert not chat.contact.opt_out


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
