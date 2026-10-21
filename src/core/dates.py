"""Spanish date helpers (design.md §8.3). Ported from `slots.py` (Peluquería) and
`messages.py` (buscaBus), with `zoneinfo` instead of `pytz`."""

from collections.abc import Collection
from datetime import date, datetime, timedelta

WEEKDAYS_ES = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")
MONTHS_ES = (
    "enero",
    "febrero",
    "marzo",
    "abril",
    "mayo",
    "junio",
    "julio",
    "agosto",
    "septiembre",
    "octubre",
    "noviembre",
    "diciembre",
)


def weekday_es(d: date) -> str:
    return WEEKDAYS_ES[d.weekday()]


def format_date_es(d: date) -> str:
    """'lunes 23 de marzo' (callers capitalize it when it starts a line)."""
    return f"{weekday_es(d)} {d.day} de {MONTHS_ES[d.month - 1]}"


def next_days(
    now: datetime, n_calendar_days: int, *, skip_weekdays: Collection[int] = ()
) -> list[date]:
    """Days from today (in `now`'s zone) to today + `n_calendar_days`, both included,
    except the weekdays in `skip_weekdays` (0 = Monday)."""
    if now.tzinfo is None:
        raise ValueError("next_days needs an aware datetime (the tenant's clock)")
    today = now.date()
    days = (today + timedelta(days=i) for i in range(n_calendar_days + 1))
    return [d for d in days if d.weekday() not in skip_weekdays]
