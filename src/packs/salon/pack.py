"""Salon pack declaration: booking, management and per-calendar sweep."""

from pathlib import Path

from core.pack import Pack, Periodic
from packs.salon import health, summary, sweep
from packs.salon.config import SalonConfig
from packs.salon.conversation import handle
from packs.salon.messages import TEMPLATE_CONFIRMATION, TEMPLATE_REMINDER

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
)
