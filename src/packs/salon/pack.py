"""Salon pack declaration: booking, management and per-calendar sweep."""

from core.pack import Pack, Periodic, SummaryMetric
from packs.salon import health, sweep
from packs.salon.config import SalonConfig
from packs.salon.conversation import handle
from packs.salon.messages import TEMPLATE_CONFIRMATION, TEMPLATE_REMINDER

pack = Pack(
    name="salon",
    config_schema=SalonConfig,
    state_version=1,
    handle_message=handle,
    needs_calendar=True,
    periodic=[Periodic("calendar_sweep", every_min=15, handler=sweep.run, max_delay_min=60)],
    health=health.check,
    templates=[TEMPLATE_CONFIRMATION, TEMPLATE_REMINDER],
    summary_metrics=[
        SummaryMetric("booking_created", "Citas creadas"),
        SummaryMetric("booking_cancelled", "Citas canceladas"),
        SummaryMetric("booking_revenue", "Ingresos estimados", unit="eur"),
    ],
)
