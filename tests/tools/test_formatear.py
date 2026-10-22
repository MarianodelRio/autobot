"""tests/tools/test_formatear.py — formatear.py es idempotente y no cambia datos."""

from __future__ import annotations

from pathlib import Path

from packs.bus import formato
from tools.bus_formatear import formatear_texto

LINEAS_DIR = (
    Path(__file__).parents[2]
    / "src"
    / "packs"
    / "bus"
    / "tests"
    / "fixtures"
    / "horarios_real"
    / "lineas"
)


def _parse_lineas_dir(lineas_dir: Path) -> dict[str, list[tuple[str, ...]]]:
    """Extrae, por fichero, la lista de filas (tuplas de valores) de todas
    las tablas, para comparar el modelo de datos antes/después de formatear."""
    resultado = {}
    for path in sorted(lineas_dir.glob("*.yaml")):
        import yaml

        datos = yaml.safe_load(path.read_text(encoding="utf-8"))
        filas_totales = []
        for entrada in datos.get("horarios", []):
            _cabecera, filas = formato._parse_tabla(entrada["tabla"])
            for fila in filas:
                filas_totales.append(tuple(fila.valores))
        resultado[path.name] = filas_totales
    return resultado


def test_formatear_es_idempotente(tmp_path: Path) -> None:
    destino = tmp_path / "lineas"
    destino.mkdir()
    for path in LINEAS_DIR.glob("*.yaml"):
        (destino / path.name).write_text(path.read_text(encoding="utf-8"), encoding="utf-8")

    primeras = {}
    for path in sorted(destino.glob("*.yaml")):
        original = path.read_text(encoding="utf-8")
        formateado_1 = formatear_texto(original)
        formateado_2 = formatear_texto(formateado_1)
        assert formateado_1 == formateado_2, f"{path.name}: no es idempotente"
        primeras[path.name] = formateado_1


def test_formatear_no_cambia_los_datos(tmp_path: Path) -> None:
    destino = tmp_path / "lineas"
    destino.mkdir()
    for path in LINEAS_DIR.glob("*.yaml"):
        (destino / path.name).write_text(path.read_text(encoding="utf-8"), encoding="utf-8")

    antes = _parse_lineas_dir(destino)

    for path in destino.glob("*.yaml"):
        original = path.read_text(encoding="utf-8")
        path.write_text(formatear_texto(original), encoding="utf-8")

    despues = _parse_lineas_dir(destino)
    assert antes == despues


TABLA_CON_ESPERA_Y_BUS = """\
nombre: Prueba
horarios:
  - temporada: anual
    dias: lunes-viernes
    tabla: |
      COR VAC PNR PVN BLQ
      10:30 11:00 11:55>12:30P 12:50 13:20 | bus:cor-1030
      13:10 13:40 14:30 14:50 15:20 | bus:x P01
"""


def test_formatear_conserva_llegada_salida_y_bus_y_es_idempotente() -> None:
    uno = formatear_texto(TABLA_CON_ESPERA_Y_BUS)
    dos = formatear_texto(uno)
    assert uno == dos
    # la celda `llegada>salida` con su letra sobrevive intacta, y el `bus:`
    # sigue tras el `|`
    assert "11:55>12:30P" in uno
    assert "| bus:cor-1030" in uno
    assert "| bus:x P01" in uno

    # y los datos parseados no cambian
    def filas(texto: str) -> list[tuple[tuple[str, ...], ...]]:
        import yaml

        datos = yaml.safe_load(texto)
        _cab, fs = formato._parse_tabla(datos["horarios"][0]["tabla"])
        return [(tuple(f.valores), tuple(f.bus), tuple(f.pendientes)) for f in fs]

    assert filas(TABLA_CON_ESPERA_Y_BUS) == filas(uno)
