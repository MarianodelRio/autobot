"""`RecordMetric("schedule_query")` only on a found itinerary (`_resultado`'s
`con_salidas` branch), on the production conversation harness directly: the legacy
`Conv` wrapper in `compat.py` has no access to `PackResult.actions`."""

from datetime import date, timedelta

from core.testing.harness import Conversation
from packs.bus.pack import pack
from packs.bus.tests.compat import CONFIG, datos_reales

HOY = date(2026, 9, 23)  # miércoles, dentro de vigencia


def chat(now: str = "2026-09-23T00:00:00+02:00") -> Conversation:
    return Conversation(pack, config=CONFIG, data=datos_reales(), now=now)


def test_a_found_itinerary_emits_schedule_query() -> None:
    bus = chat()
    bus.press("menu_horarios", check=False)
    bus.press("loc:pozoblanco", check=False)
    bus.press("loc:cordoba", check=False)
    manana = (HOY + timedelta(days=1)).isoformat()
    bus.press(f"dia:{manana}", check=False)
    assert [a.kind for a in bus.metrics] == ["schedule_query"]


def test_menu_alone_emits_no_metric() -> None:
    bus = chat()
    bus.press("menu_horarios", check=False)
    assert bus.metrics == []


def test_a_day_with_no_service_on_any_line_emits_no_metric() -> None:
    bus = chat("2026-12-22T00:00:00+01:00")
    bus.press("menu_horarios", check=False)
    bus.press("loc:pozoblanco", check=False)
    bus.press("loc:cordoba", check=False)
    bus.press("dia:2026-12-25", check=False)  # 25 Dec: sin_servicio on every line
    assert bus.metrics == []
