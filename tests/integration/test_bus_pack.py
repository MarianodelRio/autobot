"""The bus pack end to end: a tenant with its timetable in `datasets/timetable/`,
loaded by the registry and queried through the real runtime (webhook → route →
process_event → send), by its WhatsApp and by its Telegram main channel."""

import json
import shutil
from collections.abc import Callable, Iterator
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
import yaml
from django.core.management import call_command
from pytest_django import Settings

from core.clock import SystemClock
from flowpilot.channels import adapters, views
from flowpilot.channels.ratelimit import WindowLimiter
from flowpilot.runtime import process
from flowpilot.tenancy.registry import get_registry
from packs.bus.datos import Datos
from packs.bus.pack import DATASET_DIR
from packs.bus.pack import pack as bus_pack
from packs.bus.tests.compat import CONFIG, HORARIOS_REAL
from packs.registry import PACKS as REGISTERED
from tests.integration.helpers import (
    Providers,
    drain,
    fixture,
    post_tg,
    post_wa,
    providers,  # noqa: F401 (fixture)
    tg_tenant,
    wa_press,
    wa_tenant,
    wa_text,
)
from tests.tenancy.helpers import PACKS, TG_SECRETS, WA_SECRETS, write_secrets

pytestmark = [
    pytest.mark.django_db(transaction=True, databases=["default", "owner"]),
    pytest.mark.usefixtures("clean_jobs"),
]

Setup = Callable[..., None]


@pytest.fixture
def bus_tenants(
    tmp_path: Path, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> Iterator[Setup]:
    """Like the `tenants` fixture, but each tenant also gets the frozen timetable."""
    settings.TENANTS_DIR = tmp_path / "tenants"
    settings.SECRETS_FILE = tmp_path / "secrets.yaml"
    monkeypatch.setattr("packs.registry.PACKS", PACKS | {"bus": bus_pack})
    monkeypatch.setattr(views, "limiter", WindowLimiter())
    monkeypatch.setattr(process, "contact_limiter", WindowLimiter(limit=20, window_s=60))

    def setup(*docs: dict[str, Any]) -> None:
        for doc in docs:
            folder = tmp_path / "tenants" / doc["slug"]
            folder.mkdir(parents=True)
            (folder / "tenant.yaml").write_text(yaml.safe_dump(doc))
            shutil.copytree(HORARIOS_REAL, folder / DATASET_DIR)
        write_secrets(
            tmp_path,
            {
                d["slug"]: WA_SECRETS if d["channel"]["type"] == "whatsapp" else TG_SECRETS
                for d in docs
            },
        )
        get_registry.cache_clear()
        call_command("sync_tenants", stdout=None)

    yield setup
    get_registry.cache_clear()


def autocares(**config: Any) -> dict[str, Any]:
    return wa_tenant("wa", pack="bus", config=CONFIG.model_dump(mode="json") | config)


def test_the_bus_pack_is_registered() -> None:
    assert REGISTERED["bus"] is bus_pack


def test_the_registry_loads_the_timetable(bus_tenants: Setup) -> None:
    bus_tenants(autocares())
    tenant = get_registry().by_slug["wa"]
    assert tenant.degraded == []
    assert isinstance(tenant.data, Datos)
    assert tenant.data.menu_origen[0] == "cordoba"


def test_an_unknown_start_menu_town_degrades_the_tenant(bus_tenants: Setup) -> None:
    bus_tenants(autocares(start_menu_towns=["Cordobilla"]))
    tenant = get_registry().by_slug["wa"]
    assert any("Cordobilla" in reason for reason in tenant.degraded)


@pytest.fixture
def wednesday(monkeypatch: pytest.MonkeyPatch) -> None:
    """The tenant's clock on Wednesday 23/09/2026 at 10:00 (inside the timetable)."""

    def now(self: SystemClock) -> datetime:
        return datetime(2026, 9, 23, 10, 0, tzinfo=self.tz)

    monkeypatch.setattr(SystemClock, "now", now)


@pytest.mark.usefixtures("wednesday")
def test_a_full_query_through_the_whatsapp_main_channel(
    bus_tenants: Setup, monkeypatch: pytest.MonkeyPatch
) -> None:
    bus_tenants(autocares())
    sent: list[dict[str, Any]] = []

    def meta(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        return httpx.Response(200, json={"messages": [{"id": f"wamid.{len(sent)}"}]})

    monkeypatch.setattr(
        adapters.WHATSAPP, "client", httpx.Client(transport=httpx.MockTransport(meta))
    )
    for body in (
        wa_text("hola"),
        wa_press("menu_horarios"),
        wa_text("Pozoblanco"),
        wa_text("Córdoba"),
    ):
        assert post_wa(body) == 200
        drain()
    assert sent[-1]["type"] == "interactive"
    assert sent[-1]["interactive"]["header"]["text"] == "🚌 Pozoblanco → Córdoba"
    assert post_wa(wa_text("24/9/2026")) == 200
    drain()
    body = sent[-1]["interactive"]["body"]["text"]
    assert "📅 Jueves 24/09" in body


@pytest.mark.usefixtures("wednesday")
def test_a_full_query_through_a_telegram_main_channel(
    bus_tenants: Setup,
    providers: Providers,  # noqa: F811 (the imported fixture)
) -> None:
    bus_tenants(tg_tenant("tg", pack="bus", config=CONFIG.model_dump(mode="json")))
    update_ids = iter(range(820_000_001, 829_999_999))
    token = TG_SECRETS["bot_token"]

    def say_tg(text: str) -> None:
        body = json.loads(fixture("telegram/message.json"))
        body["update_id"] = next(update_ids)
        body["message"]["text"] = text
        assert post_tg(json.dumps(body).encode()) == 200
        drain()

    def press_tg(data: str) -> None:
        body = json.loads(fixture("telegram/callback_query.json"))
        body["update_id"] = next(update_ids)
        body["callback_query"]["id"] = f"cb{body['update_id']}"
        body["callback_query"]["data"] = data
        assert post_tg(json.dumps(body).encode()) == 200
        drain()

    chat = 100000001  # in testers.main of tg_tenant
    say_tg("hola")
    press_tg("menu_horarios")
    say_tg("Pozoblanco")
    press_tg("loc:cordoba")
    press_tg("dia:2026-09-24")
    result = providers.texts(chat, token=token)[-1]
    assert result.startswith("🚌 Pozoblanco → Córdoba\n📅 Jueves 24/09")
    assert providers.buttons(chat)[-3:] == ["otro_dia", "vuelta", "otra_consulta"]
    # Through the tenant's own bot, never the test bot or Meta.
    assert all(where.startswith(f"{token}/") for where, _ in providers.telegram)
    assert providers.meta == []
