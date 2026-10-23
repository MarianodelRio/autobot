"""View, move, cancel, special events and proactive ownership in both channels."""

from dataclasses import replace
from datetime import datetime, timedelta

import pytest

from core.errors import TransientError
from core.testing.harness import Conversation
from packs.salon.models import CalendarEvent
from packs.salon.tests.test_booking import choose
from packs.salon.tests.test_config import configuration


def book(salon: Conversation) -> str:
    choose(salon)
    salon.send("Lucía")
    return str(salon.calendar.created[-1].gcal_id)


def move(salon: Conversation) -> None:
    salon.press("back_to_menu")
    salon.press("menu_move")
    salon.press("move_appt:0")
    salon.press("service_corte")
    salon.press("day_2026-03-24")
    if salon.state["step"] == "BOOK_PERIOD":
        salon.press("period_morning")
    salon.press("hour_11:00")


def test_view_and_cancel(salon: Conversation) -> None:
    gcal_id = book(salon)
    salon.press("back_to_menu")
    salon.press("menu_view").expect(text_contains="24/03/2026 10:00")
    salon.press("back_to_menu")
    salon.press("menu_cancel")
    salon.press("cancel_appt:0").expect(text_contains="cancelada")
    assert salon.calendar.get_event(gcal_id) is None
    assert salon.notifications[-1].kind == "booking_cancelled"


def test_move_creates_then_cancels_and_replays(salon: Conversation) -> None:
    old = book(salon)
    move(salon)
    assert salon.calendar.get_event(old) is None
    assert salon.calendar.created[-1].start.hour == 11
    assert salon.calendar.created[-1].private["fp_key"].startswith("move:")
    assert salon.calendar.calls.index("insert_event") < salon.calendar.calls.index("cancel_event")
    salon.replay().expect(text_contains="movida")
    assert len(salon.calendar.created) == 2
    assert salon.calendar.cancelled == [old]


def test_move_failed_cancellation_preserves_new_booking_and_notifies(salon: Conversation) -> None:
    old = book(salon)
    salon.calendar.fail("cancel_event", TransientError("offline"))
    move(salon)
    assert salon.calendar.get_event(old) is not None
    assert len(salon.calendar.created) == 2
    assert salon.notifications[-1].kind == "move_cancel_failed"
    salon.turns[-1].expect(text_contains="No hemos podido cancelar")


def test_stale_cancel_selection_checks_current_owner(salon: Conversation) -> None:
    gcal_id = book(salon)
    salon.press("back_to_menu")
    salon.press("menu_cancel")
    event = salon.calendar.events[gcal_id]
    salon.calendar.add(replace(event, private=event.private | {"fp_contact": "somebody-else"}))
    salon.press("cancel_appt:0").expect(text_contains="No se encontró")
    assert salon.calendar.cancelled == []


@pytest.mark.parametrize("operation", ["reminder_confirm", "reminder_cancel", "booking_cancel"])
def test_foreign_proactive_button_is_rejected(salon: Conversation, operation: str) -> None:
    gcal_id = book(salon)
    event = salon.calendar.events[gcal_id]
    salon.calendar.add(replace(event, private=event.private | {"fp_contact": "foreign"}))
    salon.press(f"{operation}:{gcal_id}", check=False).expect(text_contains="No se encontró")
    assert salon.calendar.cancelled == []


def test_proactive_confirmation_from_any_state(salon: Conversation) -> None:
    gcal_id = book(salon)
    salon.press("back_to_menu")
    salon.press("menu_book")
    salon.press(f"reminder_confirm:{gcal_id}", check=False).expect(text_contains="confirmada")
    assert "Estado: confirmada" in salon.calendar.events[gcal_id].description
    assert salon.state == {}
    salon.press(f"booking_cancel:{gcal_id}", check=False).expect(text_contains="cancelada")
    salon.press(f"booking_cancel:{gcal_id}", check=False)
    assert salon.calendar.cancelled == [gcal_id]


def test_legacy_booking_with_external_id_can_be_managed(salon: Conversation) -> None:
    start = datetime.fromisoformat("2026-03-25T10:00:00+01:00")
    salon.calendar.add(
        CalendarEvent(
            "legacy",
            "Corte - Lucía",
            f"WaId: {salon.contact.external_id}",
            start,
            start + timedelta(minutes=30),
        )
    )
    salon.send("hola")
    salon.press("menu_cancel")
    salon.press("cancel_appt:0").expect(text_contains="cancelada")


def test_manual_phone_booking_is_owned(salon: Conversation) -> None:
    if salon.contact.phone is None:
        return
    start = datetime.fromisoformat("2026-03-25T10:00:00+01:00")
    salon.calendar.add(
        CalendarEvent(
            "manual",
            "Corte - Lucía",
            "Teléfono: +34 600 000 001",
            start,
            start + timedelta(minutes=30),
        )
    )
    salon.send("hola")
    salon.press("menu_cancel")
    salon.press("cancel_appt:0").expect(text_contains="cancelada")


def test_event_active_and_inactive(salon: Conversation) -> None:
    salon.config = configuration(
        special_event={"active": True, "name": "Feria", "days": {"2026-03-29": ["10:00-11:00"]}}
    )
    salon.send("hola").expect(list_includes="Cita Feria")
    salon.press("menu_book_event")
    salon.press("service_corte")
    assert salon.state["days"] == ["2026-03-29"]
    salon.press("day_2026-03-29")
    salon.press("hour_10:00")
    salon.send("Lucía").expect(text_contains="confirmada")
    salon.config = configuration()
    salon.press("back_to_menu")
    salon.press("menu_book_event", check=False).expect(list_includes="Pedir cita")
    assert salon.state == {}


def test_event_disabled_mid_conversation(salon: Conversation) -> None:
    salon.config = configuration(
        special_event={"active": True, "name": "Feria", "days": {"2026-03-29": ["10:00-11:00"]}}
    )
    salon.send("hola")
    salon.press("menu_book_event")
    salon.config = configuration()
    salon.press("service_corte").expect(list_includes="Pedir cita")
    assert salon.calendar.created == []


def test_contact_information(salon: Conversation) -> None:
    salon.config = configuration(info_text="Estamos en la plaza. " * 100)
    salon.send("hola").expect(list_includes="Contacto")
    salon.press("menu_info").expect(text_contains="Estamos en la plaza.")
