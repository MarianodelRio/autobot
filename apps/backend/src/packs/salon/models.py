"""Calendar events used by the pack's in-memory test calendar."""

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class CalendarEvent:
    gcal_id: str
    summary: str
    description: str
    start: datetime
    end: datetime
    all_day: bool = False
    created: datetime | None = None
    status: str = "confirmed"
    private: dict[str, str] = field(default_factory=dict)
