"""Declaration of the bus pack."""

from pathlib import Path
from typing import Any

from pydantic import BaseModel

from core.pack import Pack, TenantInfo
from packs.bus import conversation, datos, loader, summary
from packs.bus.config import BusConfig

DATASET_DIR = Path("datasets") / "timetable"  # relative to the tenant dataset root
TIMETABLE_DATASET = "timetable"


def load_data(tenant: TenantInfo, config: BaseModel, path: Path) -> datos.Datos:
    """Validate and load the tenant's timetable, and resolve `start_menu_towns` against
    it. Any error (an invalid dataset, an unknown town) degrades the tenant."""
    assert isinstance(config, BusConfig)
    return datos.cargar(path / DATASET_DIR, config.start_menu_towns)


def dataset_summary(dataset: str, path: Path) -> dict[str, Any]:
    """Validates a timetable on its own, without any tenant's `start_menu_towns`
    (ADR-013): what the dataset library stores and the panel shows when choosing or
    reviewing an entry, without ever loading its raw content."""
    if dataset != TIMETABLE_DATASET:
        raise ValueError(f"dataset desconocido para bus: {dataset!r}")
    horarios = loader.cargar(path)
    modelo = horarios.modelo
    towns = sorted(
        loc.nombre
        for lid, loc in modelo.localidades.items()
        if loc.pendiente is None and horarios.localidad_viajes.get(lid)
    )
    return {
        "lineas": len(modelo.lineas),
        "pueblos": towns,
        "viajes": sum(len(v) for v in horarios.localidad_viajes.values()),
    }


pack = Pack(
    template=Path(__file__).parent / "template",
    template_blank=("business_name", "contact_phone", "start_menu_towns"),
    name="bus",
    config_schema=BusConfig,
    state_version=1,
    conversation_timeout_min=30,
    handle_message=conversation.handle,
    load_data=load_data,
    dataset_summary=dataset_summary,
    summary=summary.summarize,
)
