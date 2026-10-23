from dataclasses import replace
from datetime import timedelta

from core.errors import PermanentError
from core.idem import IdemKeys
from core.testing.harness import Conversation
from packs.salon.models import CalendarEvent
from packs.salon.tests.test_config import configuration


def upcoming(
    salon: Conversation,
    *,
    manual: bool = False,
    created_hours_ago: int = 1,
    gcal_id: str = "upcoming",
) -> CalendarEvent:
    now = salon.clock.now()
    event = CalendarEvent(
        gcal_id,
        "Corte - Lucía",
        "Nombre: Lucía\nTelefono: +34600000001",
        now + timedelta(hours=24),
        now + timedelta(hours=24, minutes=30),
        created=now - timedelta(hours=created_hours_ago),
        private={} if manual else {"fp_contact": str(salon.contact.id), "fp_key": "booking"},
    )
    salon.calendar.add(event)
    return event


def test_reminder_keys_are_stable_across_sweeps(salon: Conversation) -> None:
    salon.config = configuration(reminders_enabled=True)
    upcoming(salon)
    first = salon.run_periodic("calendar_sweep")
    second = salon.run_periodic("calendar_sweep")
    assert len(first) == 1 and first == second
    assert salon.proactive[-1].idem_key.startswith("reminder:upcoming:")
    assert salon.proactive[-1].button_payloads == [
        "reminder_confirm:upcoming",
        "reminder_cancel:upcoming",
    ]
    assert salon.calendar.calls.count("list_events") == 2


def test_manual_confirmation_cutoff_and_status(salon: Conversation) -> None:
    salon.config = configuration(
        manual_confirmations_enabled=True,
        manual_confirmations_since=salon.clock.now() - timedelta(hours=2),
    )
    recent = upcoming(salon, manual=True)
    upcoming(salon, manual=True, created_hours_ago=3, gcal_id="old")
    actions = salon.run_periodic("calendar_sweep")
    assert len(actions) == 1 and salon.proactive[-1].idem_key == "confirm:upcoming"
    assert "Estado: pendiente" in salon.calendar.events[recent.gcal_id].description
    assert "Estado:" not in salon.calendar.events["old"].description
    assert salon.run_periodic("calendar_sweep") == actions


def test_confirmed_manual_status_is_preserved(salon: Conversation) -> None:
    salon.config = configuration(
        manual_confirmations_enabled=True,
        manual_confirmations_since=salon.clock.now() - timedelta(hours=2),
    )
    event = upcoming(salon, manual=True)
    salon.calendar.add(replace(event, description=event.description + "\nEstado: confirmada"))
    salon.run_periodic("calendar_sweep")
    assert "patch_description" not in salon.calendar.calls


def test_blocks_all_day_cancelled_and_outside_window_are_ignored(salon: Conversation) -> None:
    salon.config = configuration(reminders_enabled=True)
    event = upcoming(salon)
    salon.calendar.add(replace(event, gcal_id="block", private={}, description=""))
    salon.calendar.add(replace(event, gcal_id="all-day", all_day=True))
    salon.calendar.add(replace(event, gcal_id="cancelled", status="cancelled"))
    salon.calendar.add(replace(event, gcal_id="later", start=event.start + timedelta(hours=3)))
    assert len(salon.run_periodic("calendar_sweep")) == 1


def test_invalid_contact_and_long_callback_are_skipped(salon: Conversation) -> None:
    salon.config = configuration(reminders_enabled=True)
    event = upcoming(salon)
    salon.calendar.add(replace(event, private={"fp_key": "key", "fp_contact": "invalid"}))
    upcoming(salon, gcal_id="a" * 100)
    assert salon.run_periodic("calendar_sweep") == []


def test_disabled_sweep_does_no_io(salon: Conversation) -> None:
    assert salon.run_periodic("calendar_sweep") == []
    assert salon.calendar.calls == []


def test_health_reports_access_failure_without_error_details(salon: Conversation) -> None:
    assert salon.pack.health is not None
    ctx = salon._context(None, {}, IdemKeys(None))
    assert salon.pack.health(ctx) == []
    salon.calendar.fail("check_access", PermanentError("credential-value-must-not-appear"))
    issue = salon.pack.health(ctx)[0]
    assert issue.code == "calendar_unavailable" and "credential" not in issue.message
