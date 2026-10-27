"""Declaration of the bus pack."""

from pathlib import Path

from pydantic import BaseModel

from core.pack import Pack, SummaryMetric, TenantInfo
from packs.bus import conversation, datos
from packs.bus.config import BusConfig

DATASET_DIR = Path("datasets") / "timetable"  # inside tenants/<slug>/


def load_data(tenant: TenantInfo, config: BaseModel, path: Path) -> datos.Datos:
    """Validate and load the tenant's timetable, and resolve `start_menu_towns` against
    it. Any error (an invalid dataset, an unknown town) degrades the tenant."""
    assert isinstance(config, BusConfig)
    return datos.cargar(path / DATASET_DIR, config.start_menu_towns)


pack = Pack(
    name="bus",
    config_schema=BusConfig,
    state_version=1,
    conversation_timeout_min=30,
    handle_message=conversation.handle,
    load_data=load_data,
    summary_metrics=[SummaryMetric("schedule_query", "Consultas de horario")],
)
