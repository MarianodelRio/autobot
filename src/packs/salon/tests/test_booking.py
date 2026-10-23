"""Booking scenarios through the production conversation harness and both renderers."""

from datetime import datetime, timedelta

from core.errors import TransientError
from core.testing.harness import Conversation
from packs.salon.models import CalendarEvent
from packs.salon.tests.test_config import configuration


def choose(salon: Conversation, service: str = "corte", slot: str = "10:00") -> None:
    salon.send("hola")
    salon.press("menu_book")
    salon.press(f"service_{service}")
    salon.press("day_2026-03-24")
    if salon.state["step"] == "BOOK_PERIOD":
        salon.press("period_morning")
    salon.press(f"hour_{slot}").expect(text_contains="nombre")


def test_full_booking(salon: Conversation) -> None:
    choose(salon)
    salon.send("Lucía García").expect(text_contains="¡Tu cita está confirmada!")
    event = salon.calendar.created[0]
    assert event.summary == "Corte de pelo - Lucía García"
    assert event.start == datetime.fromisoformat("2026-03-24T10:00:00+01:00")
    assert event.end - event.start == timedelta(minutes=30)
    assert event.private["fp_contact"] == str(salon.contact.id)
    assert event.private["fp_service"] == "corte"
    assert ("Telefono:" in event.description) == (salon.contact.phone is not None)
    assert len(event.gcal_id) == 32
    assert salon.locks == ["cal:2026-03-24"]
    assert salon.contact.display_name == "Lucía García"
    assert salon.notifications[0].kind == "booking_created"


def test_replayed_booking_is_not_duplicated(salon: Conversation) -> None:
    choose(salon)
    salon.send("Lucía")
    salon.replay().expect(text_contains="¡Tu cita está confirmada!")
    assert len(salon.calendar.created) == 1
    assert len(salon.notifications) == 1


def test_limit_failure_is_open_but_creation_failure_recovers(salon: Conversation) -> None:
    salon.calendar.fail("list_contact_events", TransientError("offline"))
    choose(salon)
    salon.calendar.fail("insert_event", TransientError("offline"))
    salon.send("Lucía").expect(text_contains="problema")
    assert salon.state == {} and salon.calendar.created == []
    salon.replay().expect(text_contains="¡Tu cita está confirmada!")
    assert len(salon.calendar.created) == 1


def test_another_contact_takes_the_slot(salon: Conversation) -> None:
    choose(salon)
    start = datetime.fromisoformat("2026-03-24T10:00:00+01:00")
    salon.calendar.add(CalendarEvent("busy", "Ocupado", "", start, start + timedelta(minutes=30)))
    salon.send("Lucía").expect(text_contains="Ese horario ya no está disponible")
    assert salon.calendar.created == []
    assert "10:00" not in salon.state["all_slots"]


def test_limit_and_existing_legacy_booking(salon: Conversation) -> None:
    salon.config = configuration(max_active_bookings=1)
    start = datetime.fromisoformat("2026-03-25T10:00:00+01:00")
    salon.calendar.add(
        CalendarEvent(
            "old",
            "Corte - Lucía",
            f"WaId: {salon.contact.external_id}",
            start,
            start + timedelta(minutes=30),
        )
    )
    salon.send("hola")
    salon.press("menu_book").expect(text_contains="máximo")
    assert salon.calendar.created == []


def test_only_days_with_slots_and_one_range_read(salon: Conversation) -> None:
    salon.config = configuration(opening_hours={"martes": ["10:00-10:30"]}, booking_window_days=1)
    salon.send("hola")
    salon.press("menu_book")
    before = salon.calendar.calls.count("list_events")
    salon.press("service_corte").expect(list_includes="Martes 24 de marzo")
    assert salon.state["days"] == ["2026-03-24"]
    assert salon.calendar.calls.count("list_events") == before + 1


def test_no_free_day(salon: Conversation) -> None:
    salon.config = configuration(opening_hours={"domingo": ["10:00-10:30"]}, booking_window_days=1)
    salon.send("hola")
    salon.press("menu_book")
    salon.press("service_corte").expect(text_contains="No hay horarios")
    assert salon.state == {}


def test_known_name_audio_and_validation(salon: Conversation) -> None:
    choose(salon)
    salon.unsupported().expect(text_contains="mensaje de texto")
    salon.send("L").expect(text_contains="entre 2 y 100")
    salon.send("L" * 101).expect(text_contains="entre 2 y 100")
    salon.press("use_name").expect(text_contains="¡Tu cita está confirmada!")
    assert salon.calendar.created[0].summary.endswith("Lucía")


def test_tampered_hour_and_state_return_to_menu(salon: Conversation) -> None:
    choose(salon)
    salon.state = {"step": "BOOK_HOUR", "slots": ["broken"]}
    salon.press("hour_broken", check=False).expect(list_includes="Pedir cita")
    assert salon.state == {}


def test_long_presence_is_respected(salon: Conversation) -> None:
    choose(salon, "mechas", "11:00")
    assert "11:30" not in salon.state["all_slots"]
    salon.send("Lucía")
    event = salon.calendar.created[0]
    assert event.end - event.start == timedelta(minutes=60)


def test_day_closed_by_calendar(salon: Conversation) -> None:
    salon.config = configuration(booking_window_days=1)
    start = datetime.fromisoformat("2026-03-24T00:00:00+01:00")
    salon.calendar.add(
        CalendarEvent("closed", "[CFG] CERRADO", "", start, start + timedelta(days=1), all_day=True)
    )
    salon.send("hola")
    salon.press("menu_book")
    salon.press("service_corte")
    assert "2026-03-24" not in salon.state["days"]


def test_text_outside_name_returns_to_menu(salon: Conversation) -> None:
    salon.send("hola")
    salon.press("menu_book")
    salon.send("corte").expect(list_includes="Pedir cita")
    assert salon.state == {}
