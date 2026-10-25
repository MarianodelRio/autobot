"""Port of Peluqueria's Calendar client; no cache, globals or personal-data logs."""

import re
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from datetime import time as day_time
from typing import Any
from zoneinfo import ZoneInfo

import google_auth_httplib2  # type: ignore[import-untyped]
import httplib2  # type: ignore[import-untyped]
from google.auth.exceptions import RefreshError, TransportError
from google.oauth2 import service_account
from googleapiclient.discovery import build  # type: ignore[import-untyped]
from googleapiclient.errors import HttpError  # type: ignore[import-untyped]

from core.errors import PermanentError, TransientError
from core.text import fold, strip_html


class CalendarTransientError(TransientError):
    pass


class CalendarPermanentError(PermanentError):
    pass


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


def service(credentials_file: str) -> Any:
    credentials = service_account.Credentials.from_service_account_file(  # type: ignore[no-untyped-call]
        credentials_file, scopes=["https://www.googleapis.com/auth/calendar.events"]
    )
    return build(
        "calendar",
        "v3",
        http=google_auth_httplib2.AuthorizedHttp(credentials, http=httplib2.Http(timeout=10)),
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
        self._observe = observe or (lambda status: None)
        self._calendar_id = calendar_id
        self._credentials_file = credentials_file
        self._api = api
        self._sleep = sleep
        self._tz = ZoneInfo(timezone)

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
            try:
                request = getattr(self.api.events(), operation)(
                    calendarId=self._calendar_id, **kwargs
                )
                result = request.execute(num_retries=0)
                self._observe("ok")
                return result
            except HttpError as exc:
                status = int(exc.resp.status)
                if status not in (429, 500, 502, 503, 504):
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
            except OSError, TimeoutError, TransportError:
                pass
            if attempt < 2:
                self._sleep(0.2 * (2**attempt))
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
        if start.tzinfo is None:
            raise ValueError("Calendar window needs an aware datetime")
        return self._list(start, None)

    def _list(self, start: datetime, end: datetime | None) -> list[Event]:
        events: list[Event] = []
        token = None
        for _ in range(10):
            bounds = {"timeMin": start.isoformat()}
            if end is not None:
                bounds["timeMax"] = end.isoformat()
            raw = self._request(
                "list", **bounds, singleEvents=True, orderBy="startTime", pageToken=token
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
            raw = self._call("get", eventId=gcal_id)
        except HttpError as exc:
            if exc.resp.status in (404, 410):
                return None
            raise CalendarPermanentError(f"Calendar request refused ({exc.resp.status})") from None
        if raw.get("status") == "cancelled":
            return None
        return self._event(raw)

    def insert_event(self, event: Mapping[str, Any], gcal_id: str) -> Event:
        try:
            raw = self._call("insert", body=dict(event) | {"id": gcal_id})
        except HttpError as exc:
            if exc.resp.status == 409:
                existing = self.get_event(gcal_id)
                if existing is not None:
                    return existing
            raise CalendarPermanentError(f"Calendar insert refused ({exc.resp.status})") from None
        result = self._event(raw)
        if result.gcal_id != gcal_id or result.status == "cancelled":
            raise CalendarPermanentError("Calendar did not confirm insertion")
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
            self._request("patch", eventId=gcal_id, body={"description": description})
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
                "patch", eventId=gcal_id, body={"extendedProperties": {"private": private}}
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
