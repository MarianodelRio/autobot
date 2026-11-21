import dataclasses
import json
from datetime import UTC, datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest
from pydantic import BaseModel

from core.actions import ContactRef, NotifyOwner, UpdateContact
from core.clock import Clock, SystemClock
from core.idem import IdemKeys
from core.messages import IncomingMessage
from core.pack import Pack, PackContext, PackResult, Periodic
from core.proactive import ProactiveMessage, TemplateSpec
from core.replies import Button, Buttons, List, Row, Section, Text
from core.serialization import Outbound, dump_outbound, load_outbound

EVENT = UUID("01920000-0000-7000-8000-000000000001")
TEMPLATE = TemplateSpec(
    name="recordatorio_cita",
    language="es_ES",
    text="Recuerda que tienes cita el {1} a las {2}. ¿Confirmas tu asistencia?",
    buttons=["Confirmar", "Cancelar"],
)

OUTBOUND: list[Outbound] = [
    Text("Hola 👋 *bienvenido*"),
    Buttons("¿Qué quieres hacer?", [Button("menu_book", "Pedir cita")]),
    Buttons("Elige", [Button("a", "A"), Button("b", "B")], header="Cabecera", footer="Pie"),
    List(
        "Elige un día",
        "Ver días",
        [
            Section("Esta semana", [Row("day_1", "Jueves 9", "3 huecos"), Row("day_2", "Viernes")]),
            Section(None, [Row("more", "Más días")]),
        ],
        header="Días",
        footer="Pie",
    ),
    ProactiveMessage(
        TEMPLATE, ["9 de octubre", "17:00"], ["reminder_confirm:x", "reminder_cancel:x"]
    ),
]


@pytest.mark.parametrize("out", OUTBOUND, ids=lambda o: type(o).__name__)
def test_outbound_round_trip_through_json(out: Outbound) -> None:
    stored = json.loads(json.dumps(dump_outbound(out)))
    assert load_outbound(stored) == out


def test_unknown_payload_type_is_rejected() -> None:
    with pytest.raises(ValueError, match="Unknown"):
        load_outbound({"type": "sticker"})


@pytest.mark.parametrize(
    "value",
    [
        IncomingMessage("text", "hola", None, datetime(2026, 10, 5, tzinfo=UTC)),
        Text("x"),
        Button("a", "A"),
        TEMPLATE,
        ContactRef(phone="+34600000001"),
        NotifyOwner("booking_created", "Nueva cita", "notify:booking_created:x"),
        UpdateContact(opt_out=True),
    ],
    ids=lambda v: type(v).__name__,
)
def test_contract_values_are_immutable(value: object) -> None:
    field = dataclasses.fields(value)[0].name  # type: ignore[arg-type]
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(value, field, None)


def test_contact_ref_needs_exactly_one_target() -> None:
    assert ContactRef(contact_id=EVENT).phone is None
    with pytest.raises(ValueError):
        ContactRef()
    with pytest.raises(ValueError):
        ContactRef(contact_id=EVENT, phone="+34600000001")


def test_idem_keys() -> None:
    idem = IdemKeys(EVENT)
    assert idem.event("booking") == f"booking:{EVENT}"
    assert idem.event("booking") == IdemKeys(EVENT).event("booking")
    assert idem.stable("reminder:abc:2026-10-09T17:00") == "reminder:abc:2026-10-09T17:00"
    with pytest.raises(RuntimeError):
        IdemKeys(None).event("booking")


def test_pack_declaration_defaults() -> None:
    class ToyConfig(BaseModel):
        greeting: str = "Hola"

    def handle(ctx: PackContext, msg: IncomingMessage) -> PackResult:
        return PackResult(replies=[Text("Hola")])

    pack = Pack(
        name="toy",
        config_schema=ToyConfig,
        state_version=1,
        handle_message=handle,
        periodic=[Periodic("sweep", every_min=15, handler=lambda ctx: [])],
        templates=[TEMPLATE],
    )
    assert pack.conversation_timeout_min == 30
    assert not pack.needs_calendar and pack.load_data is None
    assert pack.periodic[0].max_delay_min == 60
    # A result means "no change" by default, and its lists are not shared between results.
    result = PackResult()
    assert result.replies == [] and result.actions == [] and result.state is None
    assert PackResult().replies is not result.replies


def test_system_clock_is_a_clock_in_the_tenant_zone() -> None:
    madrid = ZoneInfo("Europe/Madrid")
    tokyo = ZoneInfo("Asia/Tokyo")
    clock: Clock = SystemClock(madrid)
    now = clock.now()
    assert now.tzinfo == madrid
    assert abs(now - datetime.now(UTC)) < timedelta(seconds=5)
    # The same instant, shown with each zone's own offset.
    other = SystemClock(tokyo).now()
    assert other.tzinfo == tokyo
    assert other.utcoffset() == timedelta(hours=9)
    assert other.utcoffset() != now.utcoffset()
