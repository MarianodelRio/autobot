"""Holidays, the name step, cancellation guards, moving, DST and the other hardening
scenarios, through the production conversation harness and both renderers."""

from datetime import datetime, timedelta
from typing import Any

import pytest

from core.replies import Buttons
from core.testing.harness import Conversation
from packs.salon.testing import CalendarEvent
from tests.packs.salon.test_booking import choose
from tests.packs.salon.test_config import configuration
from tests.packs.salon.test_management import book

HOLIDAYS = {"country": "ES", "subdivision": "MD"}


def open_booking(salon: Conversation, service: str = "corte") -> None:
    salon.send("hola")
    salon.press("menu_book")
    salon.press(f"service_{service}")


def all_day(gcal_id: str, summary: str, day: str) -> CalendarEvent:
    start = datetime.fromisoformat(f"{day}T00:00:00+01:00")
    return CalendarEvent(gcal_id, summary, "", start, start + timedelta(days=1), all_day=True)


# ── Holidays ──────────────────────────────────────────────────────────


def test_public_holidays_are_not_offered(salon: Conversation) -> None:
    # 2026-04-02 (Maundy Thursday) and 04-03 (Good Friday) fall inside the 21-day window.
    salon.config = configuration(holidays=HOLIDAYS)
    open_booking(salon)
    days = salon.state["days"]
    assert "2026-04-01" in days and "2026-04-02" not in days and "2026-04-03" not in days
    assert "2026-04-04" in days


def test_without_a_holiday_calendar_only_the_weekday_counts(salon: Conversation) -> None:
    open_booking(salon)
    assert "2026-04-03" in salon.state["days"]


def test_extra_closing_days_and_open_exceptions(salon: Conversation) -> None:
    salon.config = configuration(
        holidays=HOLIDAYS | {"closed_dates": ["2026-03-25"], "open_dates": ["2026-04-03"]}
    )
    open_booking(salon)
    days = salon.state["days"]
    assert "2026-03-25" not in days  # a local feast, closed
    assert "2026-04-03" in days  # a holiday the business opens
    assert "2026-04-02" not in days


def test_the_calendar_still_decides_on_a_holiday(salon: Conversation) -> None:
    """`[CFG] HORARIO` opens a holiday for that day; `[CFG] CERRADO` closes any day."""
    salon.config = configuration(holidays=HOLIDAYS)
    salon.calendar.add(all_day("open", "[CFG] HORARIO 10:00-12:00", "2026-04-03"))
    salon.calendar.add(all_day("closed", "[CFG] CERRADO", "2026-04-01"))
    open_booking(salon)
    days = salon.state["days"]
    assert "2026-04-03" in days and "2026-04-01" not in days


def test_a_holiday_added_after_choosing_the_hour_is_caught_under_the_lock(
    salon: Conversation,
) -> None:
    salon.config = configuration(holidays=HOLIDAYS | {"open_dates": ["2026-04-03"]})
    salon.send("hola")
    salon.press("menu_book")
    salon.press("service_corte")
    salon.press("day_2026-04-03")
    if salon.state["step"] == "BOOK_PERIOD":
        salon.press("period_morning")
    salon.press("hour_10:00")
    salon.config = configuration(holidays=HOLIDAYS)  # the owner closes it meanwhile
    salon.send("Lucía").expect(text_contains="Ese horario ya no está disponible")
    assert salon.calendar.created == []


def test_the_special_event_is_not_closed_by_holidays(salon: Conversation) -> None:
    salon.config = configuration(
        holidays=HOLIDAYS,
        special_event={"active": True, "name": "Boda", "days": {"2026-04-03": ["10:00-12:00"]}},
    )
    salon.send("hola")
    salon.press("menu_book_event")
    salon.press("service_corte")
    assert salon.state["days"] == ["2026-04-03"]


# ── The name step ──────────────────────────────────────────────────────


def test_the_name_prompt_offers_cancel_and_the_known_name(salon: Conversation) -> None:
    choose(salon)
    last = salon.turns[-1]
    buttons = [r for r in last.replies if isinstance(r, Buttons)][-1]
    assert [b.title for b in buttons.buttons] == ["Usar Lucía", "❌ Cancelar"]
    salon.press("back_to_menu").expect(list_includes="Pedir cita")
    assert salon.state == {} and salon.calendar.created == []


@pytest.mark.parametrize(
    "word", ["cancelar", "Cancelar", "volver", "atrás", "salir", "No", "no.", "hola", "gracias"]
)
def test_escape_words_are_not_names(salon: Conversation, word: str) -> None:
    choose(salon)
    salon.send(word).expect(list_includes="Pedir cita")
    assert salon.state == {} and salon.calendar.created == []


@pytest.mark.parametrize("text", ["1234", "!!!", "-- 12 --"])
def test_a_name_needs_a_letter(salon: Conversation, text: str) -> None:
    choose(salon)
    salon.send(text).expect(
        text_contains="al menos una letra", buttons=["Usar Lucía", "❌ Cancelar"]
    )
    assert salon.state["step"] == "BOOK_NAME" and salon.calendar.created == []


def test_markup_and_line_breaks_are_removed_from_the_name(salon: Conversation) -> None:
    choose(salon)
    salon.send("*Lucía*\n_García_").expect(text_contains="confirmada")
    assert salon.calendar.created[0].summary == "Corte de pelo - Lucía García"
    assert "\n" not in salon.calendar.created[0].description.split("Nombre:")[1].split("\n")[0]


def test_alta_and_baja_are_names_in_the_name_step(salon: Conversation) -> None:
    choose(salon)
    salon.send("Alta").expect(text_contains="confirmada")
    assert salon.calendar.created[0].summary == "Corte de pelo - Alta"
    assert not salon.contact.opt_out


def test_alta_and_baja_still_are_commands_elsewhere(salon: Conversation) -> None:
    salon.send("hola")
    salon.press("menu_book")
    salon.send("baja").expect(text_contains="ya no te enviaré")
    salon.send("alta").expect(text_contains="volverás a recibir")


def test_the_name_step_reacts_to_a_stale_button_with_the_prompt(salon: Conversation) -> None:
    choose(salon)
    salon.unsupported().expect(
        text_contains="mensaje de texto", buttons=["Usar Lucía", "❌ Cancelar"]
    )
    assert salon.state["step"] == "BOOK_NAME"


# ── Cancelling asks first; the past cannot be cancelled ────────────────


def to_cancel_list(salon: Conversation) -> str:
    gcal_id = book(salon)
    salon.now("2026-03-24T09:50:00+01:00")
    salon.send("menú")
    salon.press("menu_cancel")
    return gcal_id


def test_cancelling_asks_for_confirmation(salon: Conversation) -> None:
    gcal_id = to_cancel_list(salon)
    salon.press("cancel_appt:0").expect(
        text_contains="¿Cancelar Corte de pelo del martes 24 de marzo a las 10:00?",
        buttons=["Sí, cancelar", "No"],
    )
    assert salon.calendar.get_event(gcal_id) is not None
    salon.send("sí").expect(text_contains="Elige una opción", buttons=["Sí, cancelar", "No"])
    assert salon.state["step"] == "CANCEL_CONFIRM"
    salon.press("cancel_yes").expect(text_contains="cancelada")
    assert salon.calendar.cancelled == [gcal_id]


def test_declining_the_confirmation_keeps_the_appointment(salon: Conversation) -> None:
    gcal_id = to_cancel_list(salon)
    salon.press("cancel_appt:0")
    salon.press("cancel_no").expect(text_contains="sigue en pie")
    assert salon.calendar.cancelled == [] and salon.calendar.get_event(gcal_id) is not None
    assert salon.state == {}


def test_a_stale_confirmation_button_does_not_cancel(salon: Conversation) -> None:
    gcal_id = to_cancel_list(salon)
    salon.press("cancel_appt:0")
    salon.press("back_to_menu")
    salon.press("cancel_yes", check=False).expect(list_includes="Pedir cita")
    assert salon.calendar.cancelled == [] and salon.calendar.get_event(gcal_id) is not None


def test_a_past_appointment_cannot_be_cancelled_or_moved(salon: Conversation) -> None:
    gcal_id = to_cancel_list(salon)
    salon.now("2026-03-24T10:05:00+01:00")
    salon.press("cancel_appt:0").expect(text_contains="ya ha pasado")
    assert salon.calendar.cancelled == []
    salon.send("menú")
    salon.press("menu_move").expect(text_contains="No tienes ninguna cita próxima")
    assert salon.calendar.get_event(gcal_id) is not None


@pytest.mark.parametrize("operation", ["reminder_cancel", "booking_cancel"])
def test_the_proactive_cancel_button_refuses_past_appointments(
    salon: Conversation, operation: str
) -> None:
    gcal_id = book(salon)
    salon.now("2026-03-24T10:30:00+01:00")
    salon.press(f"{operation}:{gcal_id}", check=False).expect(text_contains="ya ha pasado")
    assert salon.calendar.cancelled == []


def test_a_proactive_cancel_before_the_appointment_still_cancels(salon: Conversation) -> None:
    gcal_id = book(salon)
    salon.press(f"reminder_cancel:{gcal_id}", check=False).expect(text_contains="cancelada")
    assert salon.calendar.cancelled == [gcal_id]


# ── Moving: the appointment does not block its own replacement ──────────


def test_moving_offers_the_slots_the_appointment_itself_blocks(salon: Conversation) -> None:
    book(salon)  # corte, 10:00-10:30
    salon.press("back_to_menu")
    salon.press("menu_move")
    salon.press("move_appt:0")
    salon.press("service_corte")
    salon.press("day_2026-03-24")
    if salon.state["step"] == "BOOK_PERIOD":
        salon.press("period_morning")
    assert "10:00" in salon.state["all_slots"]
    salon.press("hour_10:00")
    assert len(salon.calendar.created) == 2  # revalidated under the lock without itself


def test_booking_anew_still_sees_the_taken_slot(salon: Conversation) -> None:
    book(salon)
    salon.press("back_to_menu")
    salon.press("menu_book")
    salon.press("service_corte")
    salon.press("day_2026-03-24")
    if salon.state["step"] == "BOOK_PERIOD":
        salon.press("period_morning")
    assert "10:00" not in salon.state["all_slots"]


# ── Free text, photos and empty days ───────────────────────────────────


def test_a_photo_at_the_menu_gets_the_generic_text(salon: Conversation) -> None:
    salon.send("hola")
    turn = salon.unsupported().expect(text_contains="audios", list_includes="Pedir cita")
    assert all("nombre" not in r.body for r in turn.replies)


def test_no_day_left_gets_its_own_text_with_the_phone(salon: Conversation) -> None:
    salon.config = configuration(opening_hours={"domingo": ["10:00-10:30"]}, booking_window_days=1)
    open_booking(salon)
    turn = salon.turns[-1].expect(text_contains="ningún día con horarios")
    assert any("600" in r.body for r in turn.replies)
    assert all("para ese día" not in r.body for r in turn.replies)


def test_a_day_that_fills_up_says_so_and_offers_the_others(salon: Conversation) -> None:
    salon.config = configuration(
        opening_hours={"martes": ["10:00-10:30"], "miercoles": ["10:00-10:30"]},
        booking_window_days=2,
    )
    open_booking(salon)
    salon.press("day_2026-03-24")
    salon.press("hour_10:00")
    start = datetime.fromisoformat("2026-03-24T10:00:00+01:00")
    salon.calendar.add(CalendarEvent("busy", "Ocupado", "", start, start + timedelta(minutes=30)))
    salon.send("Lucía").expect(text_contains="Ese horario ya no está disponible")
    assert salon.state["step"] == "BOOK_DAY" and salon.state["days"] == ["2026-03-25"]
    salon.turns[-1].expect(text_contains="No hay horarios disponibles para ese día")


# ── DST: the clock changes on 29/03 and 25/10 (2026, Europe/Madrid) ─────


def dst_salon(salon: Conversation, now: str, hours: dict[str, Any]) -> None:
    salon.now(now)
    salon.config = configuration(opening_hours=hours, booking_window_days=1, min_notice_min=0)


def test_booking_the_day_after_the_spring_change(salon: Conversation) -> None:
    dst_salon(salon, "2026-03-30T08:00:00+02:00", {"lunes": ["10:00-12:00"]})
    open_booking(salon)
    salon.press("day_2026-03-30")
    salon.press("hour_10:00")
    salon.send("Lucía").expect(text_contains="confirmada")
    event = salon.calendar.created[0]
    assert event.start.isoformat() == "2026-03-30T10:00:00+02:00"
    assert event.end - event.start == timedelta(minutes=30)


def test_booking_on_the_autumn_change_day(salon: Conversation) -> None:
    dst_salon(salon, "2026-10-25T08:00:00+01:00", {"domingo": ["10:00-12:00"]})
    open_booking(salon)
    salon.press("day_2026-10-25")
    salon.press("hour_10:00")
    salon.send("Lucía").expect(text_contains="confirmada")
    assert salon.calendar.created[0].start.isoformat() == "2026-10-25T10:00:00+01:00"


def test_the_hour_skipped_by_the_spring_change_is_not_offered(salon: Conversation) -> None:
    dst_salon(salon, "2026-03-29T00:30:00+01:00", {"domingo": ["01:30-04:30"]})
    open_booking(salon)
    salon.press("day_2026-03-29")
    # 02:00 and 02:30 do not exist that night.
    assert salon.state["all_slots"] == ["01:30", "03:00", "03:30", "04:00"]


def test_the_repeated_autumn_hour_is_offered_once(salon: Conversation) -> None:
    dst_salon(salon, "2026-10-25T00:30:00+02:00", {"domingo": ["01:30-04:00"]})
    open_booking(salon)
    salon.press("day_2026-10-25")
    assert salon.state["all_slots"] == ["01:30", "02:00", "02:30", "03:00", "03:30"]
    salon.press("hour_02:30")
    salon.send("Lucía").expect(text_contains="confirmada")
    assert salon.calendar.created[0].start.isoformat() == "2026-10-25T02:30:00+02:00"
