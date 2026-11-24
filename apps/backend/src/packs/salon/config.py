"""Salon configuration: the original business rules without module globals."""

import re
from datetime import date, datetime
from decimal import Decimal
from functools import lru_cache

import holidays as holidays_lib
from holidays.utils import list_supported_countries
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from core.dates import WEEKDAY_KEYS, Weekday
from core.hours import TimeRange, parse_range, validate_ranges
from core.limits import MAX_ID_BYTES
from packs.salon.messages import SalonTexts


def sorted_ranges(ranges: list[str]) -> list[str]:
    validate_ranges(ranges)
    return sorted(ranges)


class Service(BaseModel):
    model_config = ConfigDict(extra="forbid")
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
    model_config = ConfigDict(extra="forbid")
    active: bool = False
    name: str = Field(default="", max_length=80)
    days: dict[date, list[TimeRange]] = {}

    @field_validator("days")
    @classmethod
    def validate_days(cls, days: dict[date, list[str]]) -> dict[date, list[str]]:
        return {day: sorted_ranges(ranges) for day, ranges in days.items()}

    @model_validator(mode="after")
    def validate_active(self) -> SpecialEvent:
        if self.active and (not self.name.strip() or not self.days):
            raise ValueError("un evento activo necesita nombre y días")
        return self


@lru_cache(maxsize=32)
def _public_holidays(country: str, subdivision: str | None) -> holidays_lib.HolidayBase:
    """Public holidays of the country (and region); `holidays` builds each year on first
    access, so the cached object keeps working as the years go by."""
    return holidays_lib.country_holidays(country, subdiv=subdivision)


class HolidaysConfig(BaseModel):
    """Public-holiday calendar (library `holidays`): those days are closed, unless listed in
    `open_dates`. `closed_dates` adds local feasts, holidays or any other closing day."""

    model_config = ConfigDict(extra="forbid")
    country: str = Field(default="ES", title="País", description="Código ISO del país, p. ej. ES.")
    subdivision: str | None = Field(
        default=None,
        title="Comunidad o región",
        description="Código de la comunidad autónoma (p. ej. MD, AN, CT) o vacío.",
    )
    closed_dates: list[date] = Field(
        default=[],
        max_length=366,
        title="Días de cierre adicionales",
        description="Fiestas locales, vacaciones u otros días cerrados.",
    )
    open_dates: list[date] = Field(
        default=[],
        max_length=366,
        title="Festivos en los que se abre",
        description="Días festivos en los que el negocio sí abre.",
    )

    @model_validator(mode="after")
    def validate_calendar(self) -> HolidaysConfig:
        countries = list_supported_countries()
        if self.country not in countries:
            raise ValueError(f"país no admitido: {self.country}")
        if self.subdivision is not None and self.subdivision not in countries[self.country]:
            raise ValueError(f"comunidad o región no válida para {self.country}")
        if set(self.closed_dates) & set(self.open_dates):
            raise ValueError("una fecha no puede estar a la vez en cierre y en apertura")
        return self

    def is_closed(self, day: date) -> bool:
        if day in self.closed_dates:
            return True
        return day not in self.open_dates and day in _public_holidays(
            self.country, self.subdivision
        )


class SalonConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    business_name: str = Field(
        min_length=1,
        max_length=60,
        title="Nombre del negocio",
        description="El nombre que ven los clientes en el menú del bot.",
    )
    contact_phone: str = Field(
        min_length=1,
        max_length=30,
        title="Teléfono de contacto",
        description="Para los mensajes del bot.",
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
    opening_hours: dict[Weekday, list[TimeRange]] = Field(
        min_length=1,
        title="Horario de apertura",
        description="Franjas de cada día de la semana; un día sin franjas está cerrado.",
    )
    slot_step_min: int = Field(
        default=30,
        gt=0,
        strict=True,
        title="Paso de los huecos (min)",
        description="Cada cuántos minutos empieza una hora ofrecida (30: 10:00, 10:30…).",
    )
    min_notice_min: int = Field(
        default=0,
        ge=0,
        strict=True,
        title="Antelación mínima (min)",
        description="Con cuánta antelación como mínimo se puede reservar; 0, sin límite.",
    )
    booking_window_days: int = Field(
        default=21,
        ge=1,
        le=90,
        strict=True,
        title="Ventana de reserva (días)",
        description="Cuántos días hacia delante se puede reservar (de 1 a 90).",
    )
    max_active_bookings: int = Field(
        default=5,
        ge=1,
        strict=True,
        title="Citas activas máximas por cliente",
        description="Citas futuras que puede tener a la vez un cliente; al llegar, no puede"
        " pedir otra.",
    )
    reminders_enabled: bool = Field(
        default=False,
        title="Recordatorios activados",
        description="Envía a cada cliente un recordatorio antes de su cita.",
    )
    reminder_window_hours: tuple[int, int] = Field(
        default=(23, 25),
        title="Ventana de recordatorio (horas antes)",
        description="Entre cuántas horas antes de la cita se envía el recordatorio"
        " (mínimo y máximo).",
    )
    manual_confirmations_enabled: bool = Field(
        default=False,
        title="Confirmación manual activada",
        description="Avisa a los clientes de las citas que el negocio crea a mano en su"
        " calendario.",
    )
    manual_confirmations_since: datetime | None = Field(
        default=None,
        title="Confirmación manual desde",
        description="Fecha a partir de la cual las citas nuevas exigen confirmación manual.",
    )
    holidays: HolidaysConfig | None = Field(
        default=None,
        title="Festivos",
        description="Calendario de festivos: esos días no se puede reservar.",
    )
    special_event: SpecialEvent = Field(
        default=SpecialEvent(),
        title="Evento especial",
        description="Activo, añade «Cita <nombre>» al menú con sus propios días y franjas.",
    )
    info_text: str = Field(
        default="",
        max_length=4096,
        title="Texto informativo",
        description="Se muestra al pedir información general del negocio.",
    )
    texts: SalonTexts = Field(
        default=SalonTexts(),
        title="Textos del bot",
        description="Las frases que dice el bot; cada una trae un texto de serie que se puede"
        " cambiar.",
    )

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
        # The interactive id is service_<key> (shared channel limit).
        if any(len(f"service_{key}".encode()) > MAX_ID_BYTES for key in value):
            raise ValueError("id de servicio demasiado largo")
        return value

    @field_validator("opening_hours")
    @classmethod
    def hours(cls, value: dict[Weekday, list[str]]) -> dict[Weekday, list[str]]:
        return {day: sorted_ranges(ranges) for day, ranges in value.items()}

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
        if event:
            ranges = self.special_event.days.get(day, [])
        elif self.holidays is not None and self.holidays.is_closed(day):
            ranges = []
        else:
            ranges = self.opening_hours.get(WEEKDAY_KEYS[day.weekday()], [])
        return [parse_range(r) for r in ranges]
