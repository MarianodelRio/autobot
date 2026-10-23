"""The source business config converted to the pack contract, plus every validation."""

from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from packs.salon.config import SalonConfig
from packs.salon.messages import TEMPLATE_CONFIRMATION, TEMPLATE_REMINDER


def configuration(**changes: Any) -> SalonConfig:
    raw = yaml.safe_load((Path(__file__).parent / "fixtures/config_original.yaml").read_text())
    return SalonConfig.model_validate(raw | changes)


def test_source_configuration_validates() -> None:
    cfg = configuration()
    assert cfg.business_name == "DM Barber Shop"
    assert cfg.services["mechas"].client_presence_min == 180
    assert cfg.services["mechas"].duration_min == 60
    assert cfg.booking_window_days == 21
    assert not cfg.reminders_enabled and not cfg.manual_confirmations_enabled
    assert TEMPLATE_CONFIRMATION.name == "confirmacion_cita"
    assert TEMPLATE_REMINDER.buttons == ["Confirmar", "Cancelar"]


@pytest.mark.parametrize(
    "changes",
    [
        {"business_name": " "},
        {"contact_phone": ""},
        {"calendar_id": " "},
        {"test_calendar_id": " SALON-MAIN@example.invalid "},
        {"services": {}},
        {"services": {"bad-key": {"name": "Corte", "duration_min": 30, "client_presence_min": 30}}},
        {"services": {"corte": {"name": "Corte", "duration_min": 60, "client_presence_min": 30}}},
        {"services": {"corte": {"name": "Corte", "duration_min": 0, "client_presence_min": 30}}},
        {
            "services": {
                "corte": {
                    "name": "Corte",
                    "price_eur": -1,
                    "duration_min": 30,
                    "client_presence_min": 30,
                }
            }
        },
        {"opening_hours": {}},
        {"opening_hours": {"monday": ["10:00-14:00"]}},
        {"opening_hours": {"lunes": ["25:00-26:00"]}},
        {"opening_hours": {"lunes": ["14:00-10:00"]}},
        {"opening_hours": {"lunes": ["10:00-14:00", "13:00-16:00"]}},
        {"manual_confirmations_enabled": True},
        {"manual_confirmations_since": "2026-10-01T10:00:00"},
        {"reminder_window_hours": [25, 23]},
        {"slot_step_min": 0},
        {"slot_step_min": True},
        {"min_notice_min": -1},
        {"booking_window_days": 0},
        {"max_active_bookings": 0},
        {"special_event": {"active": True}},
        {"special_event": {"days": {"2026-15-12": ["10:00-14:00"]}}},
        {"special_event": {"days": {"2026-12-25": ["14:00-10:00"]}}},
    ],
)
def test_invalid_configuration_is_rejected(changes: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        configuration(**changes)
