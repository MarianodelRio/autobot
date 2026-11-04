"""packs/bus/tests/test_pack.py — `BusConfig`, `load_data` y la declaración del pack
(el registro lo comprueba `tests/integration/test_bus_pack.py`, porque un pack no
importa `packs.registry`)."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from core.testing import sample_tenant
from packs.bus import conversation
from packs.bus.config import BusConfig
from packs.bus.datos import Datos
from packs.bus.loader import HorariosInvalidos
from packs.bus.pack import DATASET_DIR, load_data, pack
from packs.bus.tests.compat import CONFIG, HORARIOS_REAL


def _config(**cambios: Any) -> dict[str, Any]:
    base = CONFIG.model_dump(mode="json")
    base.update(cambios)
    return base


def test_la_config_de_autocares_es_valida() -> None:
    assert BusConfig.model_validate(_config()) == CONFIG
    assert CONFIG.next_day_search_days == 45


@pytest.mark.parametrize(
    "cambios",
    [
        {"business_name": ""},
        {"contact_phone": ""},
        {"start_menu_towns": []},
        {"start_menu_towns": [f"Pueblo {i}" for i in range(9)]},
        {"start_menu_towns": ["Córdoba", "cordoba"]},
        {"start_menu_towns": ["Córdoba", " ¿? "]},
        {"links": {"web": "no es una url"}},
        {"links": {"facebook": "https://example.com"}},
        {"next_day_search_days": 0},
        {"office_hours": [{"days": ["lunes"], "ranges": ["8:00-15:00"]}]},
        {"office_hours": [{"days": ["lunes"], "ranges": ["15:00-08:00"]}]},
        {"office_hours": [{"days": ["lunes"], "ranges": ["08:00-15:00", "14:00-19:00"]}]},
        {"office_hours": [{"days": ["lunes", "lunes"], "ranges": ["08:00-15:00"]}]},
        {"office_hours": [{"days": ["festivo"], "ranges": ["08:00-15:00"]}]},
        {"office_hours": [{"days": [], "ranges": ["08:00-15:00"]}]},
        {"office_hours": [{"days": ["lunes"], "ranges": []}]},
        {
            "office_hours": [
                {"days": ["lunes"], "ranges": ["08:00-15:00"]},
                {"days": ["lunes", "martes"], "ranges": ["16:00-19:00"]},
            ]
        },
    ],
)
def test_config_invalida(cambios: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        BusConfig.model_validate(_config(**cambios))


def test_franjas_contiguas_y_sin_horario_de_oficina_son_validas() -> None:
    BusConfig.model_validate(
        _config(office_hours=[{"days": ["lunes"], "ranges": ["08:00-15:00", "15:00-19:00"]}])
    )
    BusConfig.model_validate(_config(office_hours=[], links={}))


def _tenant_dir(tmp_path: Path) -> Path:
    shutil.copytree(HORARIOS_REAL, tmp_path / DATASET_DIR)
    return tmp_path


def test_load_data_lee_el_dataset_del_tenant(tmp_path: Path) -> None:
    datos = load_data(sample_tenant(), CONFIG, _tenant_dir(tmp_path))
    assert isinstance(datos, Datos)
    assert datos.menu_origen[:2] == ("cordoba", "pozoblanco")
    assert datos.matcher.buscar("pozoblnco").tipo == "confirmar"


def test_load_data_falla_con_un_pueblo_del_menu_desconocido(tmp_path: Path) -> None:
    config = BusConfig.model_validate(_config(start_menu_towns=["Córdoba", "Cordobilla"]))
    with pytest.raises(RuntimeError, match="'Cordobilla' no es una localidad"):
        load_data(sample_tenant(), config, _tenant_dir(tmp_path))


def test_load_data_falla_con_un_dataset_invalido(tmp_path: Path) -> None:
    tenant = _tenant_dir(tmp_path)
    (tenant / DATASET_DIR / "paradas.yaml").write_text("localidades: [\n", encoding="utf-8")
    with pytest.raises(HorariosInvalidos):
        load_data(sample_tenant(), CONFIG, tenant)


def test_declaracion() -> None:
    assert pack.config_schema is BusConfig
    assert pack.handle_message is conversation.handle
    assert pack.state_version == 1
    assert pack.conversation_timeout_min == 30
    # Sin avisos proactivos ni periódicas, y sin calendario.
    assert pack.periodic == [] and pack.templates == [] and not pack.needs_calendar
