"""Salon configuration: the original business rules without module globals."""

import re
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from packs.salon.messages import SalonTexts

Weekday = Literal["lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo"]
DAYS: tuple[Weekday, ...] = (
    "lunes",
    "martes",
    "miercoles",
    "jueves",
    "viernes",
    "sabado",
    "domingo",
)
TimeRange = Annotated[str, Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d-([01]\d|2[0-3]):[0-5]\d$")]


def validate_ranges(ranges: list[str]) -> list[str]:
    spans = sorted(r.split("-") for r in ranges)
    if not spans or any(a >= b for a, b in spans):
        raise ValueError("los tramos deben ser no vacíos y estar ordenados")
    if any(a[1] > b[0] for a, b in zip(spans, spans[1:], strict=False)):
        raise ValueError("los tramos se solapan")
    return sorted(ranges)


class Service(BaseModel):
    name: str = Field(min_length=1, max_length=24)
    price_eur: Decimal | None = Field(default=None, ge=0, allow_inf_nan=False)
    duration_min: int = Field(gt=0, strict=True)
    client_presence_min: int = Field(gt=0, strict=True)

    @model_validator(mode="after")
    def validate_presence(self) -> Service:
        if not self.name.strip() or self.duration_min > self.client_presence_min:
            raise ValueError("nombre o tiempo de presencia del servicio no válido")
        return self


class SpecialEvent(BaseModel):
    active: bool = False
    name: str = Field(default="", max_length=80)
    days: dict[date, list[TimeRange]] = {}

    @field_validator("days")
    @classmethod
    def validate_days(cls, days: dict[date, list[str]]) -> dict[date, list[str]]:
        return {day: validate_ranges(ranges) for day, ranges in days.items()}

    @model_validator(mode="after")
    def validate_active(self) -> SpecialEvent:
        if self.active and (not self.name.strip() or not self.days):
            raise ValueError("un evento activo necesita nombre y días")
        return self


class SalonConfig(BaseModel):
    business_name: str = Field(min_length=1, title="Nombre del negocio")
    contact_phone: str = Field(
        min_length=1, title="Teléfono de contacto", description="Para los mensajes del bot."
    )
    calendar_id: str = Field(
        min_length=1,
        title="Calendario de Google",
        description="Id del calendario de Google Calendar usado para las reservas.",
    )
    services: dict[str, Service] = Field(
        min_length=1,
        max_length=9,
        title="Servicios",
        description="Hasta 9; la clave es el id interno.",
    )
    opening_hours: dict[Weekday, list[TimeRange]] = Field(min_length=1, title="Horario de apertura")
    slot_step_min: int = Field(default=30, gt=0, strict=True, title="Paso de los huecos (min)")
    min_notice_min: int = Field(default=0, ge=0, strict=True, title="Antelación mínima (min)")
    booking_window_days: int = Field(
        default=21, ge=1, strict=True, title="Ventana de reserva (días)"
    )
    max_active_bookings: int = Field(
        default=5, ge=1, strict=True, title="Citas activas máximas por cliente"
    )
    reminders_enabled: bool = Field(default=False, title="Recordatorios activados")
    reminder_window_hours: tuple[int, int] = Field(
        default=(23, 25), title="Ventana de recordatorio (horas antes)"
    )
    manual_confirmations_enabled: bool = Field(default=False, title="Confirmación manual activada")
    manual_confirmations_since: datetime | None = Field(
        default=None,
        title="Confirmación manual desde",
        description="Fecha a partir de la cual las citas nuevas exigen confirmación manual.",
    )
    special_event: SpecialEvent = Field(default=SpecialEvent(), title="Evento especial")
    info_text: str = Field(
        default="",
        max_length=4096,
        title="Texto informativo",
        description="Se muestra al pedir información general del negocio.",
    )
    texts: SalonTexts = Field(default=SalonTexts(), title="Textos del bot")

    @field_validator("business_name", "contact_phone", "calendar_id")
    @classmethod
    def nonempty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("el valor no puede estar en blanco")
        return value.strip()

    @field_validator("services")
    @classmethod
    def service_keys(cls, value: dict[str, Service]) -> dict[str, Service]:
        if any(re.fullmatch(r"[a-z0-9_]+", key) is None for key in value):
            raise ValueError("id de servicio no válido")
        # The interactive id is service_<key> (64-byte shared channel limit).
        if any(len(f"service_{key}".encode()) > 64 for key in value):
            raise ValueError("id de servicio demasiado largo")
        return value

    @field_validator("opening_hours")
    @classmethod
    def hours(cls, value: dict[Weekday, list[str]]) -> dict[Weekday, list[str]]:
        return {day: validate_ranges(ranges) for day, ranges in value.items()}

    @model_validator(mode="after")
    def rules(self) -> SalonConfig:
        if self.manual_confirmations_enabled and self.manual_confirmations_since is None:
            raise ValueError("la confirmación manual necesita una fecha de inicio explícita")
        if self.manual_confirmations_since and self.manual_confirmations_since.tzinfo is None:
            raise ValueError("la fecha de confirmación manual debe llevar zona horaria")
        if not 0 <= self.reminder_window_hours[0] < self.reminder_window_hours[1]:
            raise ValueError("ventana de recordatorio no válida")
        return self

    def spans(self, day: date, *, event: bool = False) -> list[tuple[str, str]]:
        ranges = (
            self.special_event.days.get(day, [])
            if event
            else self.opening_hours.get(DAYS[day.weekday()], [])
        )
        return [(r.split("-")[0], r.split("-")[1]) for r in ranges]
