"""Doble de compatibilidad para escribir los tests de conversación e interfaz
(`test_conversation`, `test_interactive`, `test_messages`) sobre una API compacta.

Aquellos tests llamaban a `conv.handle_message(...)`, leían los payloads de
WhatsApp de un `mock_wa` y fijaban el reloj con `freeze_calendario`. Aquí lo
mismo pasa por el arnés de FlowPilot (`core.testing.Conversation`): cada
mensaje recorre las reglas comunes, `plan_sends` y los límites de los dos
canales, y las respuestas de `core.replies` se convierten al payload de
WhatsApp que leían los tests (`wa`)."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import date, datetime, time
from functools import cache
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import _Call
from zoneinfo import ZoneInfo

from core.replies import Buttons, List, Reply, Text
from core.testing import Conversation
from core.testing.harness import ChannelType
from packs.bus import conversation as flujo
from packs.bus import datos as horarios_datos
from packs.bus.config import BusConfig
from packs.bus.pack import pack

FIXTURES = Path(__file__).parent / "fixtures"
HORARIOS_REAL = FIXTURES / "horarios_real"
TZ = ZoneInfo("Europe/Madrid")

# La config de Autocares San Sebastián, en el formato de `BusConfig`.
CONFIG = BusConfig.model_validate(
    dict(
        business_name="Autocares San Sebastián",
        contact_phone="957 42 90 30",
        office_hours=[
            {"days": ["lunes", "martes", "miercoles"], "ranges": ["08:00-15:00", "17:00-19:00"]},
            {"days": ["jueves", "viernes"], "ranges": ["08:00-15:00"]},
        ],
        links={"web": "https://www.autocaressansebastian.es"},
        start_menu_towns=[
            "Córdoba",
            "Pozoblanco",
            "Peñarroya-Pueblonuevo",
            "Villanueva de Córdoba",
            "Hinojosa del Duque",
            "Belalcázar",
            "Adamuz",
            "Fuente Palmera",
        ],
    )
)
NEGOCIO_TELEFONO = CONFIG.contact_phone


@cache
def datos_reales() -> horarios_datos.Datos:
    return horarios_datos.cargar(HORARIOS_REAL, CONFIG.start_menu_towns)


def wa(reply: Reply) -> dict[str, Any]:
    """El payload de WhatsApp equivalente a esta respuesta."""
    if isinstance(reply, Text):
        return {"type": "text", "text": {"body": reply.body}}
    interactive: dict[str, Any] = {"body": {"text": reply.body}}
    if reply.header:
        interactive["header"] = {"type": "text", "text": reply.header}
    if reply.footer:
        interactive["footer"] = {"text": reply.footer}
    if isinstance(reply, Buttons):
        interactive["type"] = "button"
        interactive["action"] = {
            "buttons": [
                {"type": "reply", "reply": {"id": b.id, "title": b.title}} for b in reply.buttons
            ]
        }
    else:
        assert isinstance(reply, List)
        interactive["type"] = "list"
        interactive["action"] = {
            "button": reply.button_label,
            "sections": [
                {
                    "title": s.title,
                    "rows": [
                        {"id": r.id, "title": r.title}
                        | ({"description": r.description} if r.description else {})
                        for r in s.rows
                    ],
                }
                for s in reply.sections
            ],
        }
    return {"type": "interactive", "interactive": interactive}


def wa_all(replies: list[Reply]) -> dict[str, Any]:
    """Para constructores que devuelven varias respuestas (el resultado largo):
    el último interactivo, con el texto previo delante, como lo leían los tests."""
    *previos, ultimo = replies
    payload = wa(ultimo)
    if previos:
        textos = "\n\n".join(r.body for r in previos)
        payload["interactive"]["body"]["text"] = (
            f"{textos}\n\n{payload['interactive']['body']['text']}"
        )
    return payload


@dataclass
class _Llamadas:
    """Lo que leían los tests de un `MagicMock` de envío."""

    call_args_list: list[_Call] = field(default_factory=list)

    @property
    def call_args(self) -> _Call:
        assert self.call_args_list, "no se ha enviado nada"
        return self.call_args_list[-1]

    @property
    def call_count(self) -> int:
        return len(self.call_args_list)

    @property
    def called(self) -> bool:
        return bool(self.call_args_list)


class MockWA:
    def __init__(self) -> None:
        self._envios = {"text": _Llamadas(), "interactive": _Llamadas(), "template": _Llamadas()}

    def __getitem__(self, tipo: str) -> _Llamadas:
        return self._envios[tipo]

    def registrar(self, identifier: str, replies: list[Reply]) -> None:
        for reply in replies:
            if isinstance(reply, Text):
                self._envios["text"].call_args_list.append(
                    _Call(((identifier, reply.body), {}), two=True)
                )
            else:
                self._envios["interactive"].call_args_list.append(
                    _Call(((identifier, wa(reply)), {}), two=True)
                )


class Conv:
    """Conversación del pack sobre el arnés: un `Conversation`
    por identificador, con los datos instalados al empezar a hablar."""

    UNKNOWN_INPUT = "__unknown__"
    flujo = flujo

    def __init__(self, mock_wa: MockWA, channel: ChannelType) -> None:
        self.mock_wa = mock_wa
        self.channel = channel
        self.instalados: dict[str, horarios_datos.Datos] = {"datos": datos_reales()}
        self.ahora = datetime(2026, 9, 23, 0, 0, tzinfo=TZ)
        self._chats: dict[str, Conversation] = {}

    def _chat(self, identifier: str) -> Conversation:
        if identifier not in self._chats:
            self._chats[identifier] = Conversation(
                pack,
                config=CONFIG,
                data=self.instalados["datos"],
                channel=self.channel,
                now=self.ahora,
            )
        return self._chats[identifier]

    def fijar(self, ahora: datetime) -> None:
        self.ahora = ahora
        for chat in self._chats.values():
            chat.now(ahora)

    def handle_message(
        self, identifier: str, phone: str | None, text: str | None, interactive_id: str | None
    ) -> None:
        chat = self._chat(identifier)
        if text == self.UNKNOWN_INPUT:
            turn = chat.unsupported()
        elif interactive_id is not None:
            turn = chat.press(interactive_id, check=False)
        else:
            turn = chat.send(text or "")
        self.mock_wa.registrar(identifier, turn.replies)

    def forzar(self, identifier: str, **campos: str) -> None:
        """Fuerza campos del estado guardado."""
        self._chat(identifier).state.update(campos)

    def _get(self, identifier: str) -> SimpleNamespace:
        """El estado como lo leían los tests (`state.step`, `state.origen`…)."""
        estado = self._chat(identifier).state
        return SimpleNamespace(
            step=estado.get("step", flujo.MENU),
            campo=estado.get("campo"),
            origen=estado.get("origen"),
            destino=estado.get("destino"),
            fecha=date.fromisoformat(estado["fecha"]) if "fecha" in estado else None,
            pendiente=estado.get("pendiente"),
        )

    @property
    def _states(self) -> _Estados:
        return _Estados(self)


class _Estados:
    def __init__(self, conv: Conv) -> None:
        self.conv = conv

    def __getitem__(self, identifier: str) -> SimpleNamespace:
        return self.conv._get(identifier)

    def __contains__(self, identifier: str) -> bool:
        return identifier in self.conv._chats

    def __iter__(self) -> Iterator[str]:
        return iter(self.conv._chats)

    def clear(self) -> None:
        self.conv._chats.clear()


def congelar(conv: Conv, fecha: date, hora: tuple[int, int] | None = None) -> None:
    conv.fijar(datetime.combine(fecha, time(*(hora or (0, 0))), tzinfo=TZ))
