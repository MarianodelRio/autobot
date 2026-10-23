"""Calendar API contract, with response shapes from the source bot's tests."""

import json
from copy import deepcopy
from datetime import datetime
from typing import Any
from unittest.mock import MagicMock

import httplib2  # type: ignore[import-untyped]
import pytest
from googleapiclient.errors import HttpError  # type: ignore[import-untyped]

from integrations.google_calendar.client import (
    CalendarClient,
    CalendarPermanentError,
    CalendarTransientError,
)

START = datetime.fromisoformat("2026-10-05T10:00:00+02:00")
END = datetime.fromisoformat("2026-10-06T10:00:00+02:00")
EVENT: dict[str, Any] = {
    "id": "abc123",
    "summary": "Corte - Lucía",
    "description": "Estado: pendiente<br>Nombre: Lucía",
    "start": {"dateTime": START.isoformat()},
    "end": {"dateTime": END.isoformat()},
    "extendedProperties": {"private": {"fp_contact": "contact"}},
}


def error(status: int) -> HttpError:
    return HttpError(
        httplib2.Response({"status": str(status)}), json.dumps({"error": {"code": status}}).encode()
    )


def client(*responses: Any) -> tuple[CalendarClient, MagicMock]:
    api = MagicMock()
    api.events.return_value.list.return_value.execute.side_effect = responses
    return CalendarClient("test-calendar", api=api, sleep=lambda _: None), api


def test_pagination_and_html() -> None:
    cal, api = client({"items": [EVENT], "nextPageToken": "next"}, {"items": [EVENT]})
    events = cal.list_events(START, END)
    assert len(events) == 2
    assert events[0].description == "Estado: pendiente\nNombre: Lucía"
    assert api.events().list.call_args.kwargs["pageToken"] == "next"
    assert api.events().list.call_args.kwargs["calendarId"] == "test-calendar"


def test_all_day_end_is_exclusive() -> None:
    raw = deepcopy(EVENT)
    raw.update(start={"date": "2026-10-05"}, end={"date": "2026-10-07"})
    cal, _ = client({"items": [raw]})
    event = cal.list_events(START, END)[0]
    assert event.all_day and event.end.day == 7 and event.start.tzinfo is not None


@pytest.mark.parametrize("status", [403, 404])
def test_permanent_errors(status: int) -> None:
    cal, api = client(error(status))
    with pytest.raises(CalendarPermanentError):
        cal.list_events(START, END)
    assert api.events().list.call_count == 1


@pytest.mark.parametrize("failure", [error(429), error(503), TimeoutError()])
def test_transient_failures_retry_twice(failure: Exception) -> None:
    cal, api = client(failure, failure, failure)
    with pytest.raises(CalendarTransientError):
        cal.list_events(START, END)
    assert api.events().list.call_count == 3


def test_pagination_limit_does_not_return_partial_results() -> None:
    cal, _ = client(*[{"items": [], "nextPageToken": "more"}] * 10)
    with pytest.raises(CalendarPermanentError, match="pagination"):
        cal.list_events(START, END)


def test_conflict_returns_existing_event() -> None:
    cal, api = client()
    api.events().insert.return_value.execute.side_effect = error(409)
    api.events().get.return_value.execute.return_value = EVENT
    assert cal.insert_event(EVENT, "abc123").gcal_id == "abc123"


def test_missing_event_and_repeated_cancellation() -> None:
    cal, api = client()
    api.events().get.return_value.execute.side_effect = error(404)
    api.events().delete.return_value.execute.side_effect = error(410)
    assert cal.get_event("missing") is None
    cal.cancel_event("missing")


def test_unconfirmed_writes_fail() -> None:
    cal, api = client()
    api.events().insert.return_value.execute.return_value = EVENT | {"id": "wrong"}
    with pytest.raises(CalendarPermanentError):
        cal.insert_event(EVENT, "abc123")
    api.events().get.return_value.execute.return_value = EVENT
    api.events().patch.return_value.execute.return_value = EVENT
    with pytest.raises(CalendarPermanentError):
        cal.patch_description("abc123", {"Estado": "confirmada"})
    with pytest.raises(CalendarPermanentError):
        cal.cancel_event("abc123")


def test_private_owner_wins_over_legacy_phone() -> None:
    raw = EVENT | {"description": "Telefono: +34600000001"}
    cal, _ = client({"items": [raw]})
    assert cal.list_contact_events("other", "34600000001", START, END) == []


def test_description_and_metadata_patches_preserve_other_fields() -> None:
    cal, api = client()
    api.events().get.return_value.execute.return_value = EVENT
    api.events().patch.return_value.execute.return_value = EVENT | {
        "description": "Nombre: Lucía\nEstado: confirmada"
    }
    result = cal.patch_description("abc123", {"Estado": "confirmada"})
    assert "Nombre: Lucía" in result.description
    assert result.description.count("Estado:") == 1
    api.events().patch.return_value.execute.return_value = EVENT | {
        "extendedProperties": {"private": {"fp_contact": "contact", "fp_key": "key"}}
    }
    assert cal.patch_private("abc123", {"fp_key": "key"}).private == {
        "fp_contact": "contact",
        "fp_key": "key",
    }
