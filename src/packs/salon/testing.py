"""An isolated CalendarPort in memory, with programmable errors and effects."""

from collections.abc import Mapping
from dataclasses import replace
from datetime import datetime
from typing import Any

from core.errors import PermanentError
from packs.salon.models import CalendarEvent
from packs.salon.ownership import belongs
from packs.salon.ports import CalendarPort


class FakeCalendar:
    def __init__(self) -> None:
        self.events: dict[str, CalendarEvent] = {}
        self.created: list[CalendarEvent] = []
        self.cancelled: list[str] = []
        self.calls: list[str] = []
        self.failures: dict[str, list[Exception]] = {}

    def fail(self, operation: str, exception: Exception, times: int = 1) -> None:
        self.failures.setdefault(operation, []).extend([exception] * times)

    def _check(self, operation: str) -> None:
        self.calls.append(operation)
        if self.failures.get(operation):
            raise self.failures[operation].pop(0)

    def add(self, event: CalendarEvent) -> CalendarEvent:
        self.events[event.gcal_id] = event
        return event

    def list_events(self, start: datetime, end: datetime) -> list[CalendarEvent]:
        self._check("list_events")
        return sorted(
            [
                e
                for e in self.events.values()
                if e.status != "cancelled" and e.start < end and e.end > start
            ],
            key=lambda e: e.start,
        )

    def list_future_events(self, start: datetime) -> list[CalendarEvent]:
        self._check("list_future_events")
        return sorted(
            [e for e in self.events.values() if e.status != "cancelled" and e.end > start],
            key=lambda e: e.start,
        )

    def get_event(self, gcal_id: str) -> CalendarEvent | None:
        self._check("get_event")
        event = self.events.get(gcal_id)
        return event if event is not None and event.status != "cancelled" else None

    def insert_event(self, event: Mapping[str, Any], gcal_id: str) -> CalendarEvent:
        self._check("insert_event")
        existing = self.events.get(gcal_id)
        if existing:
            if existing.status == "cancelled":
                raise PermanentError("cannot recreate cancelled event")
            return existing
        result = CalendarEvent(
            gcal_id,
            event["summary"],
            event["description"],
            datetime.fromisoformat(event["start"]["dateTime"]),
            datetime.fromisoformat(event["end"]["dateTime"]),
            created=datetime.fromisoformat(event["start"]["dateTime"]),
            private=dict(event["extendedProperties"]["private"]),
        )
        self.created.append(result)
        return self.add(result)

    def patch_description(self, gcal_id: str, fields: dict[str, str]) -> CalendarEvent:
        from packs.salon.parser import set_field

        self._check("patch_description")
        event = self.events[gcal_id]
        description = event.description
        for key, value in fields.items():
            description = set_field(description, key, value)
        return self.add(replace(event, description=description))

    def patch_private(self, gcal_id: str, fields: dict[str, str]) -> CalendarEvent:
        self._check("patch_private")
        event = self.events[gcal_id]
        return self.add(replace(event, private=event.private | fields))

    def cancel_event(self, gcal_id: str) -> None:
        self._check("cancel_event")
        event = self.events.get(gcal_id)
        if event and event.status != "cancelled":
            self.cancelled.append(gcal_id)
            self.add(replace(event, status="cancelled"))

    def list_contact_events(
        self,
        contact_id: str,
        phone: str | None,
        start: datetime,
        end: datetime,
        *,
        external_id: str | None = None,
    ) -> list[CalendarEvent]:
        self._check("list_contact_events")
        return [
            e
            for e in self.list_events(start, end)
            if not e.all_day
            and "[cfg]" not in e.summary.lower()
            and belongs(e, contact_id, phone, external_id)
        ]

    def check_access(self) -> None:
        self._check("check_access")


# Checked by mypy: the fake has the same structural interface as the API client.
_port: CalendarPort = FakeCalendar()
