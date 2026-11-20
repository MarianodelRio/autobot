"""Google Calendar client; no cache, globals or personal-data logs."""

import base64
import json
import logging
import re
import secrets as random_secrets
import threading
import time
from collections.abc import Callable, Mapping, Sequence
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

# Short, so an outage blocks an `inbound` thread for as little time as possible
# (X14: `inbound` has its own worker, but a long wait here still delays that
# contact's retries and the alert from catching on).
TIMEOUT_S = 5

log = logging.getLogger(__name__)

# A 403 with one of these reasons is Google asking to slow down, not a denial: it is
# retried with backoff like a 429 (and, after the last attempt, is transient).
_RATE_LIMIT_REASONS = frozenset(
    {"rateLimitExceeded", "userRateLimitExceeded", "quotaExceeded", "dailyLimitExceeded"}
)
# The longest horizon of `list_future_events` (the salon migration): a recurring event
# expanded with `singleEvents` would otherwise never end.
FUTURE_HORIZON = timedelta(days=730)


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
_PROBE_KEY = "fp_probe"  # D3: marks check_write_access()'s own throwaway event


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
    """The service account's own email (D1): what a client shares their calendar
    with. `None` when the file is missing or invalid — never its private key."""
    try:
        return str(_credentials(credentials_file).service_account_email)
    except OSError, ValueError:
        return None


def service(credentials_file: str) -> Any:
    credentials = _credentials(credentials_file)
    return build(
        "calendar",
        "v3",
        http=google_auth_httplib2.AuthorizedHttp(
            credentials, http=httplib2.Http(timeout=TIMEOUT_S)
        ),
        cache_discovery=False,
    )


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
    ) -> None:
        self._observer = observe
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
                self._api = service(self._credentials_file)
            except OSError, ValueError:
                raise CalendarPermanentError("Calendar credentials unavailable") from None
        return self._api

    def _call(self, operation: str, **kwargs: Any) -> Any:
        for attempt in range(3):
            base_delay = 0.2
            try:
                request = getattr(self.api.events(), operation)(
                    calendarId=self._calendar_id, **kwargs
                )
                result = request.execute(num_retries=0)
                self._observe("ok")
                return result
            except HttpError as exc:
                status = int(exc.resp.status)
                if _is_rate_limited(exc):
                    base_delay = 1.0  # asked to slow down: wait longer than for a glitch
                if status not in (429, 500, 502, 503, 504) and not _is_rate_limited(exc):
                    # An event-level 404/410 can mean either a missing event or no
                    # access, so it is no evidence of recovery from a prior denial.
                    if status not in (404, 410) or operation == "list":
                        self._observe("denied" if status in (401, 403, 404) else "error")
                    raise
            except RefreshError as exc:
                if not exc.retryable:
                    self._observe("denied")
                    raise CalendarPermanentError(
                        "Calendar credentials could not be refreshed"
                    ) from None
            except CalendarPermanentError:
                self._observe("denied")
                raise
            except OSError, TimeoutError, TransportError, HttpLib2Error:
                # Any network error (httplib2's own, a DNS failure, a reset
                # connection...) may mean the request reached Google: treated as
                # transient so the job retries, and `insert_event`'s 409 handling
                # finds the reservation already made instead of duplicating it.
                pass
            if attempt < 2:
                self._sleep(base_delay * (2**attempt))
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

    def list_future_events(self, start: datetime) -> list[Event]:
        """From `start` to `FUTURE_HORIZON` later (bounded: recurring events expand)."""
        if start.tzinfo is None:
            raise ValueError("Calendar window needs an aware datetime")
        return self._list(start, start + FUTURE_HORIZON)

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

    def patch_private(self, gcal_id: str, fields: dict[str, str]) -> Event:
        event = self.get_event(gcal_id)
        if event is None:
            raise CalendarPermanentError("Calendar event missing")
        private = event.private | fields
        result = self._event(
            self._request(
                "patch",
                eventId=gcal_id,
                body={"extendedProperties": {"private": private}},
                fields=_EVENT_FIELDS,
            )
        )
        if any(result.private.get(key) != value for key, value in private.items()):
            raise CalendarPermanentError("Calendar did not confirm metadata")
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
        """D3: proves the service account can actually write to this calendar, not
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
