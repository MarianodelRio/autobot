"""Config of the bus pack (design.md §10.4), validated like buscaBus's `config.yaml`
(`app/config.py`): non-empty name and phone, office hours with known days and
non-overlapping `HH:MM-HH:MM` ranges, and 1 to 8 distinct start-menu towns."""

import re
from typing import Annotated, Literal

from pydantic import BaseModel, Field, HttpUrl, field_validator, model_validator

from core.text import normalize

Weekday = Literal["lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo"]

_RANGE_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)-([01]\d|2[0-3]):([0-5]\d)$")

TimeRange = Annotated[str, Field(pattern=_RANGE_RE.pattern)]  # "08:00-15:00"


def _minutes(range_: str) -> tuple[int, int]:
    m = _RANGE_RE.match(range_)
    assert m is not None  # already checked by the pattern
    h1, m1, h2, m2 = (int(g) for g in m.groups())
    return h1 * 60 + m1, h2 * 60 + m2


class OfficeHours(BaseModel):
    days: list[Weekday] = Field(min_length=1)
    ranges: list[TimeRange] = Field(min_length=1)

    @field_validator("days")
    @classmethod
    def _distinct_days(cls, days: list[Weekday]) -> list[Weekday]:
        if len(set(days)) != len(days):
            raise ValueError("a day appears more than once in the block")
        return days

    @field_validator("ranges")
    @classmethod
    def _ordered_ranges(cls, ranges: list[str]) -> list[str]:
        spans = sorted(_minutes(r) for r in ranges)
        if any(start >= end for start, end in spans):
            raise ValueError("a range must start before it ends")
        if any(a[1] > b[0] for a, b in zip(spans, spans[1:], strict=False)):
            raise ValueError("ranges overlap")
        return ranges


class BusConfig(BaseModel):
    business_name: str = Field(min_length=1)
    contact_phone: str = Field(min_length=1)
    office_hours: list[OfficeHours] = []
    links: dict[Literal["web", "compra_online", "bonos", "pdf_horarios"], HttpUrl] = {}
    start_menu_towns: list[str] = Field(min_length=1, max_length=8)  # dataset town names
    next_day_search_days: int = Field(default=45, ge=1)

    @model_validator(mode="after")
    def _day_in_one_block(self) -> BusConfig:
        days = [d for block in self.office_hours for d in block.days]
        if len(set(days)) != len(days):
            raise ValueError("office_hours: a day appears in more than one block")
        return self

    @field_validator("start_menu_towns")
    @classmethod
    def _distinct_towns(cls, towns: list[str]) -> list[str]:
        keys = [normalize(t) for t in towns]
        if "" in keys:
            raise ValueError("empty town")
        if len(set(keys)) != len(keys):
            raise ValueError("duplicate town")
        return towns
