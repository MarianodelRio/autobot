"""Calendar API contract, with recorded response shapes."""

import contextlib
import json
from copy import deepcopy
from datetime import datetime
from typing import Any
from unittest.mock import MagicMock

import httplib2  # type: ignore[import-untyped]
import pytest
from google.oauth2 import service_account
from googleapiclient.errors import HttpError  # type: ignore[import-untyped]

from integrations.google_calendar.client import _EVENT_FIELDS as FIELDS
from integrations.google_calendar.client import (
    MAX_ATTEMPTS,
    TIMEOUT_S,
    CalendarClient,
    CalendarPermanentError,
    CalendarTransientError,
    service,
    service_account_email,
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


CONFIRMED = EVENT | {"description": "Nombre: Lucía\nEstado: confirmada"}


@pytest.mark.parametrize(
    ("operation", "response", "call"),
    [
        ("list", {"items": [EVENT]}, lambda cal: cal.list_events(START, END)),
        ("get", EVENT, lambda cal: cal.get_event("abc123")),
        ("insert", EVENT, lambda cal: cal.insert_event(EVENT, "abc123")),
        (
            "patch",
            CONFIRMED,
            lambda cal: cal.patch_description("abc123", {"Estado": "confirmada"}),
        ),
    ],
)
def test_reads_and_writes_request_only_the_fields_used(
    operation: str, response: dict[str, Any], call: Any
) -> None:
    """`fields=` (partial response) keeps every Calendar call from returning the full
    resource (attendees, conferenceData, reminders...) when `_event()` only reads a
    handful of fields."""
    cal, api = client()
    events = api.events.return_value
    events.get.return_value.execute.return_value = EVENT
    getattr(events, operation).return_value.execute.side_effect = [response]
    call(cal)
    expected = f"nextPageToken,items({FIELDS})" if operation == "list" else FIELDS
    assert getattr(events, operation).call_args.kwargs["fields"] == expected


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


@pytest.mark.parametrize(
    "failure",
    [
        error(503),
        TimeoutError(),
        httplib2.ServerNotFoundError("no DNS"),  # any httplib2 error is transient
    ],
)
def test_transient_failures_are_tried_twice(failure: Exception) -> None:
    cal, api = client(failure, failure, failure)
    with pytest.raises(CalendarTransientError):
        cal.list_events(START, END)
    assert api.events().list.call_count == MAX_ATTEMPTS == 2


def test_a_transient_failure_followed_by_success_is_retried_after_a_jittered_pause() -> None:
    sleeps: list[float] = []
    api = MagicMock()
    api.events.return_value.list.return_value.execute.side_effect = [error(503), {"items": []}]
    cal = CalendarClient("c", api=api, sleep=sleeps.append)
    assert cal.list_events(START, END) == []
    assert len(sleeps) == 1 and 0.1 <= sleeps[0] <= 0.3  # 0.2 s with +-50% jitter


def test_a_429_is_never_retried_in_the_client() -> None:
    sleeps: list[float] = []
    seen: list[str] = []
    api = MagicMock()
    api.events.return_value.list.return_value.execute.side_effect = [error(429), {"items": []}]
    cal = CalendarClient("c", api=api, sleep=sleeps.append, observe=seen.append)
    with pytest.raises(CalendarTransientError):
        cal.list_events(START, END)
    assert api.events().list.call_count == 1 and sleeps == [] and seen == ["error"]


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


def test_description_patch_preserves_other_fields() -> None:
    cal, api = client()
    api.events().get.return_value.execute.return_value = EVENT
    api.events().patch.return_value.execute.return_value = EVENT | {
        "description": "Nombre: Lucía\nEstado: confirmada"
    }
    result = cal.patch_description("abc123", {"Estado": "confirmada"})
    assert "Nombre: Lucía" in result.description
    assert result.description.count("Estado:") == 1


def test_service_caches_credentials_per_file(monkeypatch: pytest.MonkeyPatch) -> None:
    """Loading and parsing the service account file (and its RSA key) is expensive:
    reused across calls for the same file within the process, instead of redone for
    every `CalendarClient` (one per pack context built)."""
    import integrations.google_calendar.client as client_module

    calls: list[str] = []

    def fake_from_file(path: str, **_: Any) -> MagicMock:
        calls.append(path)
        return MagicMock()

    monkeypatch.setattr(service_account.Credentials, "from_service_account_file", fake_from_file)
    monkeypatch.setattr(client_module, "build", lambda *a, **k: None)
    service("a.json")
    service("a.json")
    service("b.json")
    assert calls == ["a.json", "b.json"]


def test_service_account_email_reads_the_credentials_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The panel shows this so a client knows what to share their calendar with.
    monkeypatch.setattr(
        service_account.Credentials,
        "from_service_account_file",
        lambda *a, **k: MagicMock(service_account_email="autobot@proyecto.iam.gserviceaccount.com"),
    )
    assert service_account_email("d1-test-sa.json") == "autobot@proyecto.iam.gserviceaccount.com"


def test_service_account_email_is_none_without_a_valid_file() -> None:
    assert service_account_email("/does/not/exist.json") is None


def test_service_uses_a_short_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """A short timeout per Calendar call, so an outage blocks an `inbound` thread
    for as little time as possible (it also has its own worker, so it never blocks
    `outbound`/`periodic` either)."""
    import integrations.google_calendar.client as client_module

    monkeypatch.setattr(
        service_account.Credentials, "from_service_account_file", lambda *a, **k: MagicMock()
    )
    seen = {}

    def fake_build(*args: Any, **kwargs: Any) -> None:
        seen["http"] = kwargs["http"]

    monkeypatch.setattr(client_module, "build", fake_build)
    service("creds.json")
    assert seen["http"].timeout == TIMEOUT_S
    assert TIMEOUT_S <= 2.5


def test_the_real_client_satisfies_the_pack_protocol() -> None:
    from packs.salon.ports import CalendarPort

    cal, api = client({"items": []})
    port: CalendarPort = cal
    port.check_access()
    assert api.events().list.call_args.kwargs["maxResults"] == 1


def rate_limit_error(reason: str, status: int = 403) -> HttpError:
    body = {"error": {"code": status, "errors": [{"reason": reason, "domain": "usageLimits"}]}}
    return HttpError(httplib2.Response({"status": str(status)}), json.dumps(body).encode())


@pytest.mark.parametrize("reason", ["rateLimitExceeded", "userRateLimitExceeded", "quotaExceeded"])
def test_a_403_for_rate_limits_is_transient_and_never_retried(reason: str) -> None:
    seen: list[str] = []
    sleeps: list[float] = []
    api = MagicMock()
    api.events.return_value.list.return_value.execute.side_effect = [
        rate_limit_error(reason),
        {"items": []},
    ]
    cal = CalendarClient("c", api=api, sleep=sleeps.append, observe=seen.append)
    with pytest.raises(CalendarTransientError):
        cal.list_events(START, END)
    assert api.events().list.call_count == 1 and sleeps == []
    assert seen == ["error"]  # never `denied`


def test_a_403_for_another_reason_is_still_a_denial() -> None:
    cal, api = client(rate_limit_error("forbidden"))
    with pytest.raises(CalendarPermanentError):
        cal.list_events(START, END)
    assert api.events().list.call_count == 1


def test_a_failing_observer_never_breaks_a_call() -> None:
    def boom(status: str) -> None:
        raise RuntimeError("observer down")

    api = MagicMock()
    api.events.return_value.list.return_value.execute.return_value = {"items": [EVENT]}
    cal = CalendarClient("c", api=api, observe=boom)
    assert len(cal.list_events(START, END)) == 1
    api.events.return_value.list.return_value.execute.side_effect = error(403)
    with pytest.raises(CalendarPermanentError):
        cal.list_events(START, END)


def test_cancelling_with_a_404_tells_a_deleted_event_from_lost_access() -> None:
    cal, api = client({"items": []})  # check_access succeeds: the calendar is reachable
    api.events().delete.return_value.execute.side_effect = error(404)
    api.events().get.return_value.execute.side_effect = error(404)
    cal.cancel_event("gone")  # already deleted: fine

    cal, api = client(error(404))  # the listing is a 404 too: access lost
    api.events().delete.return_value.execute.side_effect = error(404)
    with pytest.raises(CalendarPermanentError):
        cal.cancel_event("gone")


def test_a_conflict_with_a_cancelled_event_reactivates_it() -> None:
    cal, api = client()
    api.events().insert.return_value.execute.side_effect = error(409)
    api.events().get.return_value.execute.return_value = EVENT | {"status": "cancelled"}
    api.events().patch.return_value.execute.return_value = EVENT | {"status": "confirmed"}
    assert cal.insert_event(EVENT, "abc123").status == "confirmed"
    body = api.events().patch.call_args.kwargs["body"]
    assert body["status"] == "confirmed" and "id" not in body

    api.events().patch.return_value.execute.return_value = EVENT | {"status": "cancelled"}
    with pytest.raises(CalendarPermanentError):
        cal.insert_event(EVENT, "abc123")


@pytest.mark.parametrize("retryable", [True, False])
def test_refresh_failure_is_classified(retryable: bool) -> None:
    from google.auth.exceptions import RefreshError

    failure = RefreshError("token endpoint unavailable", retryable=retryable)  # type: ignore[no-untyped-call]
    cal, api = client(*[failure] * MAX_ATTEMPTS)
    with pytest.raises(CalendarTransientError if retryable else CalendarPermanentError):
        cal.list_events(START, END)
    assert api.events().list.call_count == (MAX_ATTEMPTS if retryable else 1)


@pytest.mark.parametrize("missing_status", [404, 410])
def test_observer_retains_denial_when_caller_catches_it(missing_status: int) -> None:
    from unittest.mock import Mock

    from googleapiclient.errors import HttpError
    from httplib2 import Response

    from integrations.google_calendar.client import CalendarClient, CalendarPermanentError

    service = Mock()
    service.events.return_value.list.return_value.execute.side_effect = HttpError(
        Response({"status": "403"}), b'{"error":{"message":"private"}}'
    )
    seen: list[str] = []
    client = CalendarClient("calendar", api=service, observe=seen.append)
    with contextlib.suppress(CalendarPermanentError):
        client.check_access()
    assert seen == ["denied"]
    service.events.return_value.get.return_value.execute.side_effect = error(missing_status)
    assert client.get_event("missing-event") is None
    assert seen == ["denied"]
    service.events.return_value.list.return_value.execute.side_effect = None
    service.events.return_value.list.return_value.execute.return_value = {"items": []}
    client.check_access()
    assert seen == ["denied", "ok"]


def test_check_write_access_inserts_confirms_and_deletes_a_probe_event() -> None:
    """Verified for real against the local demo calendar too (not just here)."""
    api = MagicMock()
    api.events.return_value.list.return_value.execute.side_effect = [{"items": []}]

    def fake_insert(**kwargs: Any) -> dict[str, Any]:
        body = kwargs["body"]
        return {**body, "description": ""}

    api.events.return_value.insert.return_value.execute.side_effect = lambda **_: fake_insert(
        **api.events.return_value.insert.call_args.kwargs
    )
    api.events.return_value.delete.return_value.execute.return_value = {}
    api.events.return_value.get.return_value.execute.side_effect = error(404)

    cal = CalendarClient("test-calendar", api=api, sleep=lambda _: None)
    cal.check_write_access()

    insert_body = api.events().insert.call_args.kwargs["body"]
    assert insert_body["summary"].startswith("[cfg]")
    assert insert_body["transparency"] == "transparent"
    assert insert_body["extendedProperties"]["private"] == {"fp_probe": "1"}
    assert insert_body["start"]["dateTime"].startswith("2000-01-01")
    assert api.events().delete.call_args.kwargs["eventId"] == insert_body["id"]


def test_check_write_access_clears_a_leftover_probe_first() -> None:
    api = MagicMock()
    leftover = {
        **EVENT,
        "id": "old-probe",
        "extendedProperties": {"private": {"fp_probe": "1"}},
    }
    api.events.return_value.list.return_value.execute.side_effect = [{"items": [leftover]}]

    def fake_insert(**kwargs: Any) -> dict[str, Any]:
        return {**kwargs["body"], "description": ""}

    api.events.return_value.insert.return_value.execute.side_effect = lambda **_: fake_insert(
        **api.events.return_value.insert.call_args.kwargs
    )
    api.events.return_value.delete.return_value.execute.return_value = {}
    api.events.return_value.get.return_value.execute.side_effect = error(404)

    cal = CalendarClient("test-calendar", api=api, sleep=lambda _: None)
    cal.check_write_access()

    deleted_ids = [call.kwargs["eventId"] for call in api.events().delete.call_args_list]
    assert "old-probe" in deleted_ids


def test_the_service_is_built_once_per_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    import threading

    import integrations.google_calendar.client as client_module

    built: list[str] = []
    monkeypatch.setattr(
        service_account.Credentials, "from_service_account_file", lambda *a, **k: MagicMock()
    )
    monkeypatch.setattr(
        client_module, "build", lambda *a, **k: built.append(threading.current_thread().name)
    )
    client_module.thread_service("t.json")
    client_module.thread_service("t.json")
    other = threading.Thread(target=client_module.thread_service, args=("t.json",), name="other")
    other.start()
    other.join()
    assert built == [threading.current_thread().name, "other"]


# ── time budget ──────────────────────────────────────────────────────────


def test_a_spent_budget_fails_without_calling_google() -> None:
    from integrations.google_calendar import time_budget

    seen: list[str] = []
    api = MagicMock()
    cal = CalendarClient("c", api=api, observe=seen.append)
    with time_budget(0), pytest.raises(CalendarTransientError, match="budget"):
        cal.check_access()
    api.events.assert_not_called()
    assert seen == ["error"]


def test_no_budget_means_no_limit_and_the_budget_ends_with_its_block() -> None:
    from integrations.google_calendar import time_budget

    cal, api = client({"items": []}, {"items": []})
    with time_budget(60):
        cal.check_access()
    cal.check_access()  # outside the block: not limited
    assert api.events().list.call_count == 2


def test_no_retry_pause_beyond_the_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    """The second attempt does not start if the pause would overrun the budget."""
    import integrations.google_calendar.client as client_module
    from integrations.google_calendar import time_budget

    clock = [100.0]
    monkeypatch.setattr(client_module, "_monotonic", lambda: clock[0])
    monkeypatch.setattr(client_module, "_jitter", lambda low, high: high)  # pause 0.3 s
    sleeps: list[float] = []
    cal, api = client(error(503), {"items": []})
    cal._sleep = sleeps.append
    with time_budget(0.25), pytest.raises(CalendarTransientError):
        cal.check_access()
    assert api.events().list.call_count == 1 and sleeps == []


def test_the_attempt_timeout_is_the_smaller_of_the_default_and_what_is_left(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import integrations.google_calendar.client as client_module
    from integrations.google_calendar import time_budget

    clock = [100.0]
    monkeypatch.setattr(client_module, "_monotonic", lambda: clock[0])
    http = MagicMock()
    http.timeout = TIMEOUT_S
    cal, _ = client({"items": []})
    cal._http = http
    with time_budget(1.0):
        cal.check_access()
    assert http.timeout == 1.0
    http.close.assert_called_once()


def test_the_first_attempt_does_not_inherit_the_timeout_of_a_previous_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The thread-local `Http` is reused: a message that ran with a spent budget left a
    short timeout on it, and the next message's first attempt must reset it."""
    import integrations.google_calendar.client as client_module

    http = MagicMock()
    http.timeout = 0.4  # left by a previous message on this thread
    api = MagicMock()
    api.events.return_value.list.return_value.execute.return_value = {"items": []}
    seen: list[float] = []

    def execute(**_: object) -> dict[str, list[object]]:
        seen.append(http.timeout)
        return {"items": []}

    api.events.return_value.list.return_value.execute.side_effect = execute
    monkeypatch.setattr(client_module, "thread_service", lambda _file: (api, http))
    cal = CalendarClient("c", credentials_file="creds.json")  # builds `api` lazily
    cal.check_access()
    assert seen == [TIMEOUT_S]


# ── circuit breaker in the client ─────────────────────────────────────────


def test_an_open_breaker_fails_at_once_and_a_probe_closes_it() -> None:
    from integrations.google_calendar import CircuitBreaker

    now = [0.0]
    breaker = CircuitBreaker(consecutive=2, open_s=10, clock=lambda: now[0])
    seen: list[str] = []
    api = MagicMock()
    execute = api.events.return_value.list.return_value.execute
    execute.side_effect = [error(503)] * 2 + [{"items": []}]
    cal = CalendarClient("c", api=api, sleep=lambda _: None, observe=seen.append, breaker=breaker)
    with pytest.raises(CalendarTransientError):
        cal.check_access()  # two failed attempts: the breaker opens
    assert breaker.state == "open"
    calls = execute.call_count
    with pytest.raises(CalendarTransientError, match="circuit"):
        cal.check_access()
    assert execute.call_count == calls  # Google was not called
    assert seen[-1] == "error"
    now[0] = 11.0
    cal.check_access()  # the probe
    assert breaker.state == "closed"


def test_permanent_refusals_do_not_trip_the_breaker() -> None:
    from integrations.google_calendar import CircuitBreaker

    breaker = CircuitBreaker(consecutive=2)
    cal, _ = client(*[error(403)] * 5)
    cal._breaker = breaker
    for _ in range(5):
        with pytest.raises(CalendarPermanentError):
            cal.check_access()
    assert breaker.state == "closed"
