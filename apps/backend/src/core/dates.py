"""Spanish date helpers, with `zoneinfo`."""

from datetime import date

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
