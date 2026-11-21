"""Spanish date helpers, with `zoneinfo`."""

from collections.abc import Mapping
from datetime import date, time
from typing import Literal, get_args

# Weekday keys as used in configs and datasets: lowercase, no accents.
Weekday = Literal["lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo"]
WEEKDAY_KEYS: tuple[Weekday, ...] = get_args(Weekday)
# The same days as shown to people, with accents.
WEEKDAY_LABEL: Mapping[str, str] = {
    "lunes": "lunes",
    "martes": "martes",
    "miercoles": "miércoles",
    "jueves": "jueves",
    "viernes": "viernes",
    "sabado": "sábado",
    "domingo": "domingo",
}

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
# Month name (as written in datasets) -> number 1..12.
MONTH_NUMBER = {name: number for number, name in enumerate(MONTHS_ES, start=1)}


def weekday_es(d: date) -> str:
    return WEEKDAYS_ES[d.weekday()]


def format_date_es(d: date) -> str:
    """'lunes 23 de marzo' (callers capitalize it when it starts a line)."""
    return f"{weekday_es(d)} {d.day} de {MONTHS_ES[d.month - 1]}"


def parse_hhmm(value: str) -> time:
    """'09:30' -> time(9, 30). The format is validated where the text enters the system."""
    hour, minute = value.split(":")
    return time(int(hour), int(minute))


def minutes_of(value: time | str) -> int:
    """Minutes since midnight of a time or an 'HH:MM' text."""
    if isinstance(value, str):
        value = parse_hhmm(value)
    return value.hour * 60 + value.minute
