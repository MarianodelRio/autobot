"""Salon pack declaration (periodic and health handlers added in T-5.6)."""

from core.pack import Pack
from packs.salon.config import SalonConfig
from packs.salon.conversation import handle
from packs.salon.messages import TEMPLATE_CONFIRMATION, TEMPLATE_REMINDER

pack = Pack(
    name="salon",
    config_schema=SalonConfig,
    state_version=1,
    handle_message=handle,
    needs_calendar=True,
    templates=[TEMPLATE_CONFIRMATION, TEMPLATE_REMINDER],
)
