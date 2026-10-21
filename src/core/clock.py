from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from zoneinfo import ZoneInfo


class Clock(Protocol):
    """Current time in the tenant's zone. Tests inject a fixed clock (T-1.5)."""

    def now(self) -> datetime: ...


@dataclass(frozen=True)
class SystemClock:
    tz: ZoneInfo

    def now(self) -> datetime:
        return datetime.now(self.tz)
