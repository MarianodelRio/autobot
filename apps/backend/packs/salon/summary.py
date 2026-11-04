"""The owner's summary line for `salon` (ADR-007):
citas and estimated revenue, straight from the calendar, which is the source of truth."""

from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal

from core.pack import PackContext, SummaryLine
from core.text import fold
from packs.salon.booking import calendar, configuration
from packs.salon.config import SalonConfig, Service
from packs.salon.parser import parse_cfg
from packs.salon.ports import CalEvent

_DASHES = "-–—"  # hyphen, en dash, em dash


def summarize(
    ctx: PackContext, start: datetime, end: datetime, recorded: Mapping[str, Decimal]
) -> list[SummaryLine]:
    cfg = configuration(ctx)
    count, revenue, unpriced = 0, Decimal(0), 0
    for event in calendar(ctx).list_events(start, end):
        if event.all_day or not (start <= event.start < end):
            continue  # list_events also returns events that only overlap the window
        if not is_appointment(event, cfg):
            continue
        count += 1
        key = service_of(event, cfg)
        price = cfg.services[key].price_eur if key is not None else None
        if price is None:
            unpriced += 1
        else:
            revenue += price
    return [
        SummaryLine("✂️", "Citas", Decimal(count)),
        SummaryLine(
            "💶",
            "Ingresos estimados",
            revenue,
            unit="eur",
            note=f"{unpriced} sin precio" if unpriced else None,
        ),
    ]


def is_appointment(event: CalEvent, cfg: SalonConfig) -> bool:
    """A bot event, or one whose title starts with a service name the way the bot's
    do (`"<Servicio> - <Nombre>"`); any other event is the owner's own (ADR-007)."""
    if parse_cfg(event.summary):
        return False
    if event.private.get("fp_key"):
        return True  # a bot event is always an appointment, priced or not
    return service_of(event, cfg) is not None


def service_of(event: CalEvent, cfg: SalonConfig) -> str | None:
    bot_service = event.private.get("fp_service")
    if bot_service and bot_service in cfg.services:
        return bot_service
    return _match_title(event.summary, cfg.services)


def _match_title(title: str, services: Mapping[str, Service]) -> str | None:
    normalized = _fold(title)
    matches: list[tuple[int, str]] = []
    for key, svc in services.items():
        name = _fold(svc.name)
        if not name:
            continue
        if normalized == name:
            matches.append((len(name), key))
            continue
        if normalized.startswith(name):
            rest = normalized[len(name) :].lstrip(" ")
            if rest and rest[0] in _DASHES:
                matches.append((len(name), key))
    if not matches:
        return None
    return max(matches, key=lambda m: m[0])[1]


def _fold(text: str) -> str:
    return " ".join(fold(text).split())
