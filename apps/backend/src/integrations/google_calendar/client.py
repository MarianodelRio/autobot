"""Google Calendar client; no cache, globals or personal-data logs."""

import base64
import json
import logging
import random
import re
import secrets as random_secrets
import threading
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from datetime import time as day_time
from typing import Any
from zoneinfo import ZoneInfo

import google_auth_httplib2  # type: ignore[import-untyped]
import httplib2  # type: ignore[import-untyped]
from google.auth.exceptions import RefreshError, TransportError
from google.oauth2 import service_account
from googleapiclient.discovery import build  # type: ignore[import-untyped]
from googleapiclient.errors import HttpError  # type: ignore[import-untyped]
from httplib2.error import HttpLib2Error  # type: ignore[import-untyped]

from core.errors import PermanentError, TransientError
from core.text import fold, strip_html
from integrations.google_calendar.breaker import CircuitBreaker

# Short, so an outage blocks a worker thread for as little time as possible. With
# `MAX_ATTEMPTS` it bounds a call at ~5 s plus the pause, inside the per-message budget
# (ADR-023).
TIMEOUT_S = 2.5
MAX_ATTEMPTS = 2

log = logging.getLogger(__name__)

# One breaker per process (the workers are processes, the threads share it): Google
# failing is a fact about Google, not about one calendar.
BREAKER = CircuitBreaker()

# The time a caller allows itself for everything it does with Calendar for one message
# (a monotonic deadline). Unset: no limit. Set by `time_budget`; a ContextVar so each
# thread (each job) has its own.
_deadline: ContextVar[float | None] = ContextVar("calendar_deadline", default=None)


def _monotonic() -> float:
    return time.monotonic()


def _jitter(low: float, high: float) -> float:
    return random.uniform(low, high)


@contextmanager
def time_budget(seconds: float) -> Iterator[None]:
    """Everything this thread calls on Calendar inside the block shares `seconds`: no
    attempt starts once it is spent, and an attempt's timeout never exceeds what is left
    (`CalendarTransientError` instead)."""
    token = _deadline.set(_monotonic() + seconds)
    try:
        yield
    finally:
        _deadline.reset(token)


def _remaining() -> float | None:
    deadline = _deadline.get()
    return None if deadline is None else deadline - _monotonic()


# A 403 with one of these reasons is Google asking to slow down, not a denial: it is
# transient, and never retried by the client itself (retrying a quota error only adds
# load; the job's own retry or the person's next message tries later).
_RATE_LIMIT_REASONS = frozenset(
    {"rateLimitExceeded", "userRateLimitExceeded", "quotaExceeded", "dailyLimitExceeded"}
)


def _reasons(exc: HttpError) -> set[str]:
    """The `reason`s of a Google API error (never its message, which may hold data)."""
    found: set[str] = set()
    details = getattr(exc, "error_details", None)
    if isinstance(details, list):
        found.update(str(d["reason"]) for d in details if isinstance(d, dict) and d.get("reason"))
    try:
        body = json.loads(exc.content)
        errors = body.get("error", {}).get("errors", [])
        found.update(str(e["reason"]) for e in errors if isinstance(e, dict) and e.get("reason"))
    except ValueError, AttributeError, TypeError:
        pass
    return found


def _is_rate_limited(exc: HttpError) -> bool:
    return int(exc.resp.status) == 403 and bool(_reasons(exc) & _RATE_LIMIT_REASONS)


class CalendarTransientError(TransientError):
    pass


class CalendarPermanentError(PermanentError):
    pass


# Partial response (`fields=`): only what `_event()` reads, instead of the full
# resource (attendees, conferenceData, reminders...) on every read or write.
_EVENT_FIELDS = "id,summary,description,start,end,created,status,extendedProperties/private"
_PROBE_KEY = "fp_probe"  # Marks check_write_access()'s own throwaway event


@dataclass(frozen=True)
class Event:
    gcal_id: str
    summary: str
    description: str
    start: datetime
    end: datetime
    all_day: bool = False
    created: datetime | None = None
    status: str = "confirmed"
    private: dict[str, str] = field(default_factory=dict)


_credentials_cache: dict[str, Any] = {}
_credentials_lock = threading.Lock()


def _credentials(credentials_file: str) -> Any:
    """Loading and parsing the service account file (and its RSA key) is expensive:
    cached per process instead of redone for every `CalendarClient` (one per pack
    context built)."""
    with _credentials_lock:
        cached = _credentials_cache.get(credentials_file)
        if cached is None:
            cached = service_account.Credentials.from_service_account_file(  # type: ignore[no-untyped-call]
                credentials_file, scopes=["https://www.googleapis.com/auth/calendar.events"]
            )
            _credentials_cache[credentials_file] = cached
        return cached


def service_account_email(credentials_file: str) -> str | None:
    """The service account's own email: what a client shares their calendar
    with. `None` when the file is missing or invalid — never its private key."""
    try:
        return str(_credentials(credentials_file).service_account_email)
    except OSError, ValueError:
        return None


def _service_and_http(credentials_file: str) -> tuple[Any, Any]:
    credentials = _credentials(credentials_file)
    http = httplib2.Http(timeout=TIMEOUT_S)
    api = build(
        "calendar",
        "v3",
        http=google_auth_httplib2.AuthorizedHttp(credentials, http=http),
        cache_discovery=False,
    )
    return api, http


def service(credentials_file: str) -> Any:
    return _service_and_http(credentials_file)[0]


_thread_services = threading.local()


def thread_service(credentials_file: str) -> tuple[Any, Any]:
    """The service object and its `httplib2.Http` of this thread, built once. httplib2
    is not thread-safe, so each thread has its own; the credentials (and their token)
    are the process-wide ones. Saves rebuilding the client, and re-opening the
    connection, for every pack context."""
    cache: dict[str, tuple[Any, Any]] = _thread_services.__dict__.setdefault("by_file", {})
    pair = cache.get(credentials_file)
    if pair is None:
        pair = cache[credentials_file] = _service_and_http(credentials_file)
    return pair


def _phone(value: str) -> str:
    digits = re.sub(r"\D", "", value)
    return "34" + digits if len(digits) == 9 else digits


def owned(
    event: Event,
    contact_id: str,
    phone: str | None,
    external_id: str | None,
    alias_ids: Sequence[str] = (),
) -> bool:
    if event.private.get("fp_contact"):
        return event.private["fp_contact"] in (contact_id, *alias_ids)
    description = strip_html(event.description)
    wa = re.search(r"(?im)^\s*waid\s*:\s*([^\s]+)", description)
    tel = re.search(r"(?im)^\s*tel(?:[eé]fono)?\s*:\s*([+\d][\d -]*)", description)
    return bool(
        (wa and external_id and wa[1] == external_id)
        or (tel and phone and _phone(tel[1]) == _phone(phone))
    )


class CalendarClient:
    def __init__(
        self,
        calendar_id: str,
        *,
        credentials_file: str = "",
        timezone: str = "Europe/Madrid",
        api: Any = None,
        sleep: Callable[[float], None] = time.sleep,
        observe: Callable[[str], None] | None = None,
        breaker: CircuitBreaker | None = None,
    ) -> None:
        self._observer = observe
        self._breaker = BREAKER if breaker is None else breaker
        self._http: Any = None  # the httplib2.Http behind `api`, when we built it
        self._calendar_id = calendar_id
        self._credentials_file = credentials_file
        self._api = api
        self._sleep = sleep
        self._tz = ZoneInfo(timezone)

    def _observe(self, status: str) -> None:
        """The health signal must never break a Calendar call: its failures are only logged."""
        if self._observer is None:
            return
        try:
            self._observer(status)
        except Exception:
            log.warning("calendar observer failed", exc_info=True)

    @property
    def api(self) -> Any:
        if self._api is None:
            try:
                self._api, self._http = thread_service(self._credentials_file)
            except OSError, ValueError:
                raise CalendarPermanentError("Calendar credentials unavailable") from None
        return self._api

    def _attempt_timeout(self) -> float:
        """The timeout of the next attempt, within the caller's budget."""
        remaining = _remaining()
        if remaining is None:
            return TIMEOUT_S
        if remaining < 0.1:
            self._observe("error")
            raise CalendarTransientError("Calendar time budget spent")
        return min(TIMEOUT_S, remaining)

    def _apply_timeout(self, timeout: float) -> None:
        # httplib2 reads the timeout when it opens a connection: a changed one needs the
        # cached connections closed (rare: only when the budget is nearly spent).
        if self._http is not None and self._http.timeout != timeout:
            self._http.close()
            self._http.timeout = timeout

    def _call(self, operation: str, **kwargs: Any) -> Any:
        for attempt in range(MAX_ATTEMPTS):
            base_delay = 0.2
            timeout = self._attempt_timeout()
            if not self._breaker.allow():
                # Google is not answering: fail at once, do not wait for a timeout.
                self._observe("error")
                raise CalendarTransientError("Calendar circuit open")
            started = _monotonic()
            judged = False

            def judge(ok: bool, started: float = started) -> None:
                nonlocal judged
                judged = True
                self._breaker.record(ok=ok, duration_s=_monotonic() - started)

            try:
                self._apply_timeout(timeout)
                request = getattr(self.api.events(), operation)(
                    calendarId=self._calendar_id, **kwargs
                )
                result = request.execute(num_retries=0)
                judge(True)
                self._observe("ok")
                return result
            except HttpError as exc:
                status = int(exc.resp.status)
                if status == 429 or _is_rate_limited(exc):
                    # Asked to slow down: not retried here, not a denial.
                    judge(False)
                    self._observe("error")
                    raise CalendarTransientError("Calendar rate limited") from None
                if status not in (500, 502, 503, 504):
                    # Google answered: a refusal, not an outage. An event-level 404/410
                    # can mean either a missing event or no access, so it is no evidence
                    # of recovery from a prior denial.
                    judge(True)
                    if status not in (404, 410) or operation == "list":
                        self._observe("denied" if status in (401, 403, 404) else "error")
                    raise
                judge(False)
            except RefreshError as exc:
                if not exc.retryable:
                    self._observe("denied")
                    raise CalendarPermanentError(
                        "Calendar credentials could not be refreshed"
                    ) from None
                judge(False)
            except CalendarPermanentError:
                self._observe("denied")
                raise
            except OSError, TimeoutError, TransportError, HttpLib2Error:
                # Any network error (httplib2's own, a DNS failure, a reset
                # connection...) may mean the request reached Google: treated as
                # transient so the job retries, and `insert_event`'s 409 handling
                # finds the reservation already made instead of duplicating it.
                judge(False)
            finally:
                if not judged:
                    self._breaker.abort()
            if attempt < MAX_ATTEMPTS - 1:
                delay = base_delay * (2**attempt) * _jitter(0.5, 1.5)  # jitter
                remaining = _remaining()
                if remaining is not None and remaining <= delay:
                    break  # no time left for another attempt
                self._sleep(delay)
        self._observe("error")
        raise CalendarTransientError("Calendar temporarily unavailable")

    def _request(self, operation: str, **kwargs: Any) -> Any:
        try:
            return self._call(operation, **kwargs)
        except HttpError as exc:
            raise CalendarPermanentError(f"Calendar request refused ({exc.resp.status})") from None

    def _event(self, raw: Mapping[str, Any]) -> Event:
        def moment(value: Mapping[str, str]) -> datetime:
            if "dateTime" in value:
                dt = datetime.fromisoformat(value["dateTime"])
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=ZoneInfo(value.get("timeZone", str(self._tz))))
                return dt.astimezone(self._tz)
            return datetime.combine(
                datetime.fromisoformat(value["date"]).date(), day_time(), self._tz
            )

        try:
            return Event(
                str(raw["id"]),
                str(raw.get("summary") or ""),
                strip_html(str(raw.get("description") or "")),
                moment(raw["start"]),
                moment(raw["end"]),
                "date" in raw["start"],
                datetime.fromisoformat(raw["created"]) if raw.get("created") else None,
                str(raw.get("status", "confirmed")),
                dict(raw.get("extendedProperties", {}).get("private", {})),
            )
        except KeyError, TypeError, ValueError:
            raise CalendarPermanentError("Invalid Calendar event response") from None

    def list_events(self, start: datetime, end: datetime) -> list[Event]:
        if start.tzinfo is None or end.tzinfo is None or end <= start:
            raise ValueError("Calendar window needs ordered aware datetimes")
        return self._list(start, end)

    def _list(self, start: datetime, end: datetime | None) -> list[Event]:
        events: list[Event] = []
        token = None
        for _ in range(10):
            bounds = {"timeMin": start.isoformat()}
            if end is not None:
                bounds["timeMax"] = end.isoformat()
            raw = self._request(
                "list",
                **bounds,
                singleEvents=True,
                orderBy="startTime",
                pageToken=token,
                fields=f"nextPageToken,items({_EVENT_FIELDS})",
            )
            events.extend(
                self._event(e) for e in raw.get("items", []) if e.get("status") != "cancelled"
            )
            token = raw.get("nextPageToken")
            if not token:
                return events
        raise CalendarPermanentError("Calendar pagination limit exceeded")

    def get_event(self, gcal_id: str) -> Event | None:
        try:
            raw = self._call("get", eventId=gcal_id, fields=_EVENT_FIELDS)
        except HttpError as exc:
            if exc.resp.status in (404, 410):
                return None
            raise CalendarPermanentError(f"Calendar request refused ({exc.resp.status})") from None
        if raw.get("status") == "cancelled":
            return None
        return self._event(raw)

    def insert_event(self, event: Mapping[str, Any], gcal_id: str) -> Event:
        try:
            raw = self._call("insert", body=dict(event) | {"id": gcal_id}, fields=_EVENT_FIELDS)
        except HttpError as exc:
            if exc.resp.status == 409:
                return self._resolve_conflict(event, gcal_id)
            raise CalendarPermanentError(f"Calendar insert refused ({exc.resp.status})") from None
        result = self._event(raw)
        if result.gcal_id != gcal_id or result.status == "cancelled":
            raise CalendarPermanentError("Calendar did not confirm insertion")
        return result

    def _resolve_conflict(self, event: Mapping[str, Any], gcal_id: str) -> Event:
        """A 409 on insert: the id exists. A live event is the reservation already made
        (a retried insert); a `cancelled` one (Google keeps deleted ids) is reactivated
        with the new content; anything else is an error."""
        try:
            raw = self._call("get", eventId=gcal_id, fields=_EVENT_FIELDS)
        except HttpError:
            raise CalendarPermanentError("Calendar insert conflict could not be resolved") from None
        if raw.get("status") != "cancelled":
            return self._event(raw)
        body = {k: v for k, v in dict(event).items() if k != "id"} | {"status": "confirmed"}
        result = self._event(
            self._request("patch", eventId=gcal_id, body=body, fields=_EVENT_FIELDS)
        )
        if result.status == "cancelled":
            raise CalendarPermanentError("Calendar event could not be reactivated")
        return result

    def patch_description(self, gcal_id: str, fields: dict[str, str]) -> Event:
        event = self.get_event(gcal_id)
        if event is None:
            raise CalendarPermanentError("Calendar event missing")
        lines = event.description.splitlines()
        lines = [
            line for line in lines if fold(line.partition(":")[0]) not in {fold(k) for k in fields}
        ]
        description = "\n".join([*lines, *(f"{k}: {v}" for k, v in fields.items())])
        result = self._event(
            self._request(
                "patch",
                eventId=gcal_id,
                body={"description": description},
                fields=_EVENT_FIELDS,
            )
        )
        if result.description != description:
            raise CalendarPermanentError("Calendar did not confirm description")
        return result

    def cancel_event(self, gcal_id: str) -> None:
        try:
            self._call("delete", eventId=gcal_id)
        except HttpError as exc:
            if exc.resp.status not in (404, 410):
                raise CalendarPermanentError(
                    f"Calendar delete refused ({exc.resp.status})"
                ) from None
            if exc.resp.status == 404:
                # A 404 is also what a calendar we lost access to answers: a listing
                # tells "the event is already gone" from "we cannot see the calendar"
                # (raises, and records the denial).
                self.check_access()
        if self.get_event(gcal_id) is not None:
            raise CalendarPermanentError("Calendar did not confirm cancellation")

    def list_contact_events(
        self,
        contact_id: str,
        phone: str | None,
        start: datetime,
        end: datetime,
        *,
        external_id: str | None = None,
        alias_ids: Sequence[str] = (),
    ) -> list[Event]:
        return [
            event
            for event in self.list_events(start, end)
            if not fold(event.summary).startswith("[cfg]")
            and owned(event, contact_id, phone, external_id, alias_ids)
            and not event.all_day
        ]

    def check_access(self) -> None:
        self._request("list", maxResults=1, singleEvents=True, fields="items(id)")

    def check_write_access(self) -> None:
        """Proves the service account can actually write to this calendar, not
        just read it. Inserts a throwaway event (year 2000, transparent, private,
        `[cfg]` summary, `fp_probe=1` — never `fp_key`/`fp_contact`, so neither the
        sweep nor the owner's summary ever mistake it for a booking), confirms it,
        then deletes it. Clears any leftover probe from an earlier ambiguous call
        first, so a retry never leaves one behind."""
        window_start = datetime(2000, 1, 1, tzinfo=self._tz)
        window_end = datetime(2000, 1, 2, tzinfo=self._tz)
        for leftover in self.list_events(window_start, window_end):
            if leftover.private.get(_PROBE_KEY):
                self.cancel_event(leftover.gcal_id)
        probe_id = base64.b32hexencode(random_secrets.token_bytes(16)).decode().lower()[:26]
        event = {
            "summary": "[cfg] Autobot: prueba de acceso",
            "start": {"dateTime": window_start.isoformat()},
            "end": {"dateTime": (window_start + timedelta(minutes=5)).isoformat()},
            "transparency": "transparent",
            "visibility": "private",
            "extendedProperties": {"private": {_PROBE_KEY: "1"}},
        }
        inserted = self.insert_event(event, probe_id)
        self.cancel_event(inserted.gcal_id)
