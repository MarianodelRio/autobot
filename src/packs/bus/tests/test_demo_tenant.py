"""Escenario del pack `bus` sobre el negocio de demo de la plataforma
(`tenants/demo-autobuses/`, docs/mejoras/01-bot-de-demo.md §5.10, §6). A
diferencia de `test_escenarios.py` (que usa el dataset congelado de
Autocares San Sebastián en `fixtures/`), este test lee el `tenant.yaml` y el
dataset reales del repositorio: cualquier cambio que invalide el negocio de
demo lo detecta aquí."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import yaml

from core.testing import Conversation
from packs.bus import datos as bus_datos
from packs.bus import query
from packs.bus.config import BusConfig
from packs.bus.pack import DATASET_DIR, pack

REPO_ROOT = Path(__file__).resolve().parents[4]
TENANT_DIR = REPO_ROOT / "tenants" / "demo-autobuses"

LUNES = "2026-09-21T00:00:00+02:00"  # lunes laborable, dentro de la vigencia


def _config() -> BusConfig:
    raw = yaml.safe_load((TENANT_DIR / "tenant.yaml").read_text())
    return BusConfig.model_validate(raw["config"])


def _datos(config: BusConfig) -> bus_datos.Datos:
    return bus_datos.cargar(TENANT_DIR / DATASET_DIR, config.start_menu_towns)


def test_posadas_cordoba_un_lunes_tiene_la_linea_directa_y_la_normal() -> None:
    config = _config()
    datos = _datos(config)

    consulta = query.consultar(datos.horarios, "posadas", "cordoba", date(2026, 9, 21))
    assert consulta.estado == "con_salidas"
    lineas = {lid for salida in consulta.salidas for lid in salida.lineas}
    assert "posadas-cordoba" in lineas
    assert "posadas-cordoba-directo" in lineas

    chat = Conversation(pack, config=config, data=datos, channel="telegram", now=LUNES)
    chat.send("hola").expect(buttons=["🚌 Ver horarios", "ℹ️ Contacto"])
    chat.press("menu_horarios").expect(list_includes="Posadas")
    chat.press("loc:posadas")
    chat.press("loc:cordoba")
    resultado = chat.press("dia:2026-09-21")
    texto = "\n\n".join(r.body for r in resultado.replies)
    assert "06:45" in texto and "07:00" in texto
