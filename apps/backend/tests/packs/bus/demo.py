"""Negocio ficticio de demo del pack `bus` y sus datos, para los tests del pack.

Sin relación con ningún cliente real: una comarca inventada ("Valdehoz") en
`fixtures/horarios_ficticios/`."""

from __future__ import annotations

from functools import cache
from pathlib import Path

from packs.bus import datos as horarios_datos
from packs.bus.config import BusConfig

FIXTURES = Path(__file__).parent / "fixtures"
HORARIOS_FICTICIOS = FIXTURES / "horarios_ficticios"

# Negocio ficticio de demo, sin relación con ningún cliente real.
CONFIG = BusConfig.model_validate(
    dict(
        business_name="Autobuses Ejemplo",
        contact_phone="600 00 00 00",
        office_hours=[
            {"days": ["lunes", "martes", "miercoles"], "ranges": ["08:00-15:00", "17:00-19:00"]},
            {"days": ["jueves", "viernes"], "ranges": ["08:00-15:00"]},
        ],
        links={"web": "https://www.autobuses-ejemplo.invalid"},
        start_menu_towns=[
            "Riomayor",
            "Pozoluengo",
            "Montealto",
            "Fuenteclara",
            "Odalla",
        ],
    )
)
NEGOCIO_TELEFONO = CONFIG.contact_phone


@cache
def datos_demo() -> horarios_datos.Datos:
    return horarios_datos.cargar(HORARIOS_FICTICIOS, CONFIG.start_menu_towns)
