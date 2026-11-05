from datetime import datetime, timedelta
from zoneinfo import ZoneInfo


class FixedClock:
    """A `core.clock.Clock` that only moves when the test says so. Like `SystemClock`,
    it gives the time in the tenant's zone (with its summer/winter offset)."""

    def __init__(self, at: datetime, tz: ZoneInfo) -> None:
        self.tz = tz
        self.set(at)

    def set(self, at: datetime) -> None:
        if at.tzinfo is None:
            raise ValueError("FixedClock needs an aware datetime")
        self._now = at

    def advance(self, **delta: float) -> None:
        self._now += timedelta(**delta)

    def now(self) -> datetime:
        return self._now.astimezone(self.tz)
