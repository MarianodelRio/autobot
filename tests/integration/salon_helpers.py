"""Temporary salon tenants and calendars; no real APIs or credentials."""

from collections.abc import Callable, Iterator
from typing import Any

import pytest

from autobot.runtime import context
from autobot.tenancy.registry import get_registry
from packs.salon.pack import pack
from packs.salon.testing import FakeCalendar
from packs.salon.tests.test_config import configuration
from tests.integration.helpers import tg_tenant, wa_tenant


class Calendars:
    def __init__(self) -> None:
        cfg = configuration()
        self.main = FakeCalendar()
        self.clients = {cfg.calendar_id: self.main}
        self.bound: list[str] = []

    def __call__(self, calendar_id: str, **kwargs: Any) -> FakeCalendar:
        self.bound.append(calendar_id)
        return self.clients[calendar_id]


@pytest.fixture
def salon_setup(
    tenants: Any, monkeypatch: pytest.MonkeyPatch
) -> Iterator[tuple[Callable[..., Any], Calendars]]:
    calendars = Calendars()
    monkeypatch.setattr("packs.registry.PACKS", {"salon": pack})
    monkeypatch.setattr(context, "CalendarClient", calendars)

    def setup(*, channel: str = "whatsapp", **changes: Any) -> Any:
        slug = changes.pop("slug", "salon")
        config_changes = changes.pop("config", {})
        cfg = configuration(**config_changes).model_dump(mode="json")
        builder = wa_tenant if channel == "whatsapp" else tg_tenant
        doc = builder(slug, pack="salon", config=cfg, **changes)
        tenants(doc)
        return get_registry().by_slug[slug]

    yield setup, calendars
