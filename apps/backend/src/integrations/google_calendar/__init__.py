"""Google Calendar client, bound to one calendar, independent of Django and packs."""

from integrations.google_calendar.breaker import CircuitBreaker
from integrations.google_calendar.client import (
    BREAKER,
    CalendarClient,
    CalendarPermanentError,
    CalendarTransientError,
    time_budget,
)

__all__ = [
    "BREAKER",
    "CalendarClient",
    "CalendarPermanentError",
    "CalendarTransientError",
    "CircuitBreaker",
    "time_budget",
]
