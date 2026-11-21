"""Opening-hour ranges written as 'HH:MM-HH:MM'."""

import re
from collections.abc import Sequence
from typing import Annotated

from pydantic import Field

from core.dates import minutes_of

RANGE_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d-([01]\d|2[0-3]):[0-5]\d$")

TimeRange = Annotated[str, Field(pattern=RANGE_RE.pattern)]  # "08:00-15:00"


def parse_range(value: str) -> tuple[str, str]:
    """'08:00-15:00' -> ('08:00', '15:00')."""
    start, end = value.split("-")
    return start, end


def validate_ranges(ranges: Sequence[str]) -> None:
    """Raise ValueError unless the ranges are non-empty, each starts before it ends and
    none overlap (touching is fine). Messages are shown to panel users."""
    if not ranges:
        raise ValueError("debe haber al menos un tramo")
    spans = sorted((minutes_of(a), minutes_of(b)) for a, b in map(parse_range, ranges))
    if any(start >= end for start, end in spans):
        raise ValueError("un tramo debe empezar antes de acabar")
    if any(a[1] > b[0] for a, b in zip(spans, spans[1:], strict=False)):
        raise ValueError("los tramos se solapan")
