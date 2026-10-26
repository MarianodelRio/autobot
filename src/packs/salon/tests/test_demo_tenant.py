"""Escenario del pack `salon` sobre el negocio de demo de la plataforma
(`tenants/demo-peluqueria/`, docs/mejoras/01-bot-de-demo.md §5.10, §6). Lee el
`tenant.yaml` real del repositorio y solo sustituye el marcador
`PENDIENTE-calendario-de-demo` por un `calendar_id` de prueba, para probar el
flujo completo de reserva con `FakeCalendar` sin depender de Google Calendar."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import yaml

from core.testing.harness import Conversation
from packs.salon.config import SalonConfig
from packs.salon.pack import pack
from packs.salon.testing import FakeCalendar

REPO_ROOT = Path(__file__).resolve().parents[4]
TENANT_DIR = REPO_ROOT / "tenants" / "demo-peluqueria"
MARTES = "2026-09-22T09:00:00+02:00"  # martes laborable, dentro de la ventana de reserva


def _config() -> SalonConfig:
    raw = yaml.safe_load((TENANT_DIR / "tenant.yaml").read_text())
    config = raw["config"] | {"calendar_id": "test-calendar-demo-peluqueria"}
    return SalonConfig.model_validate(config)


def test_full_booking_on_the_demo_tenant() -> None:
    config = _config()
    chat = Conversation(
        pack, config=config, channel="telegram", calendar=FakeCalendar(), now=MARTES
    )

    chat.send("hola")
    chat.press("menu_book")
    chat.press("service_corte")
    chat.press("day_2026-09-22")
    if chat.state["step"] == "BOOK_PERIOD":
        chat.press("period_morning")
    chat.press("hour_09:30").expect(text_contains="nombre")
    chat.send("Lucía García").expect(text_contains="¡Tu cita está confirmada!")

    event = chat.calendar.created[0]
    assert event.summary == "Corte de pelo - Lucía García"
    assert event.start == datetime.fromisoformat("2026-09-22T09:30:00+02:00")
    assert event.end - event.start == timedelta(minutes=30)
    assert chat.notifications[0].kind == "booking_created"
