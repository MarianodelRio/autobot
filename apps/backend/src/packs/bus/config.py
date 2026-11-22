"""Config of the bus pack: non-empty name and phone, office hours with known days and
non-overlapping `HH:MM-HH:MM` ranges, and 1 to 8 distinct start-menu towns."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator

from core.dates import Weekday
from core.hours import TimeRange, validate_ranges
from core.text import normalize

DEFAULT_DISCLAIMER = "Horarios orientativos; confirma con la compañía."


class OfficeHours(BaseModel):
    model_config = ConfigDict(extra="forbid")
    days: list[Weekday] = Field(min_length=1)
    ranges: list[TimeRange] = Field(min_length=1)

    @field_validator("days")
    @classmethod
    def _distinct_days(cls, days: list[Weekday]) -> list[Weekday]:
        if len(set(days)) != len(days):
            raise ValueError("un día aparece más de una vez en el bloque")
        return days

    @field_validator("ranges")
    @classmethod
    def _ordered_ranges(cls, ranges: list[str]) -> list[str]:
        validate_ranges(ranges)
        return ranges


class BusConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    business_name: str = Field(min_length=1, title="Nombre del negocio")
    contact_phone: str = Field(
        min_length=1,
        max_length=30,
        title="Teléfono de contacto",
        description="Para los mensajes del bot.",
    )
    office_hours: list[OfficeHours] = Field(default=[], title="Horario de oficina")
    links: dict[Literal["web", "compra_online", "bonos", "pdf_horarios"], HttpUrl] = Field(
        default={}, title="Enlaces", description="Web, compra online, bonos y PDF de horarios."
    )
    start_menu_towns: list[str] = Field(
        min_length=1,
        max_length=8,
        title="Localidades del menú inicial",
        description="Hasta 8; deben existir en el dataset de horarios.",
    )
    next_day_search_days: int = Field(
        default=45,
        ge=1,
        title="Días de búsqueda hacia delante",
        description="Cuántos días se buscan al pedir «el próximo bus».",
    )

    schedule_disclaimer: str = Field(
        default=DEFAULT_DISCLAIMER,
        max_length=200,
        title="Aviso de horarios orientativos",
        description="Línea que cierra cada respuesta de horarios; vacío para no mostrarla.",
    )

    @model_validator(mode="after")
    def _day_in_one_block(self) -> BusConfig:
        days = [d for block in self.office_hours for d in block.days]
        if len(set(days)) != len(days):
            raise ValueError("office_hours: un día aparece en más de un bloque")
        return self

    @field_validator("start_menu_towns")
    @classmethod
    def _distinct_towns(cls, towns: list[str]) -> list[str]:
        keys = [normalize(t) for t in towns]
        if "" in keys:
            raise ValueError("localidad vacía")
        if len(set(keys)) != len(keys):
            raise ValueError("localidad duplicada")
        return towns
