"""Salon pack declaration: booking, management and per-calendar sweep."""

from pathlib import Path
from typing import Any

from core.pack import Pack, Periodic
from packs.salon import health, summary, sweep
from packs.salon.config import SalonConfig
from packs.salon.conversation import handle
from packs.salon.messages import TEMPLATE_CONFIRMATION, TEMPLATE_REMINDER


def _test_calendar() -> Any:
    # Deferred: this import only happens when `manage.py chat` (L4) actually calls
    # it, so packs/salon/pack.py (always imported via the registry) never pulls
    # in its own test double just by being registered.
    from packs.salon.testing import FakeCalendar

    return FakeCalendar()


pack = Pack(
    template=Path(__file__).parent / "template",
    template_blank=("calendar_id", "contact_phone", "business_name"),
    name="salon",
    config_schema=SalonConfig,
    state_version=1,
    handle_message=handle,
    needs_calendar=True,
    periodic=[Periodic("calendar_sweep", every_min=15, handler=sweep.run, max_delay_min=60)],
    health=health.check,
    templates=[TEMPLATE_CONFIRMATION, TEMPLATE_REMINDER],
    summary=summary.summarize,
    test_calendar=_test_calendar,
)
