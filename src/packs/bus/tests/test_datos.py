"""packs/bus/tests/test_datos.py — `datos.cargar` resuelve los pueblos del menú
de inicio contra las localidades del dataset, o falla con el nombre del pueblo.
buscaBus no tenía tests propios de este módulo."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from packs.bus import datos
from packs.bus.loader import HorariosInvalidos

FIXTURES = Path(__file__).parent / "fixtures"
HORARIOS_REAL = FIXTURES / "horarios_real"


def test_cargar_resuelve_el_menu_por_nombre_normalizado() -> None:
    d = datos.cargar(HORARIOS_REAL, ["córdoba", "POZOBLANCO"])
    assert d.menu_origen == ("cordoba", "pozoblanco")
    assert d.horarios.localidad_viajes["cordoba"]


def test_cargar_pueblo_desconocido_falla_con_su_nombre() -> None:
    with pytest.raises(RuntimeError, match="'Cordobilla' no es una localidad conocida"):
        datos.cargar(HORARIOS_REAL, ["Córdoba", "Cordobilla"])


def test_cargar_no_acepta_prefijos_ni_erratas() -> None:
    with pytest.raises(RuntimeError, match="'Pozoblan' no es una localidad"):
        datos.cargar(HORARIOS_REAL, ["Pozoblan"])


def test_cargar_pueblo_duplicado_falla() -> None:
    with pytest.raises(RuntimeError, match="'cordoba' está duplicado"):
        datos.cargar(HORARIOS_REAL, ["Córdoba", "cordoba"])


def test_cargar_pueblo_sin_viajes_falla(tmp_path: Path) -> None:
    destino = tmp_path / "horarios"
    shutil.copytree(FIXTURES / "horarios_pendientes", destino)
    with pytest.raises(RuntimeError, match="no tiene ningún viaje"):
        datos.cargar(destino, ["Aldea A"])


def test_cargar_dataset_invalido_lanza_horarios_invalidos(tmp_path: Path) -> None:
    (tmp_path / "lineas").mkdir()
    with pytest.raises(HorariosInvalidos):
        datos.cargar(tmp_path, [])
