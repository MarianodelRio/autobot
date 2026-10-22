"""Fixtures del pack `bus`, portadas de `buscaBus/tests/conftest.py`. En buscaBus
instalaban los datos en un global; aquí los devuelven, porque el pack los recibe
en `ctx.data`."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from pathlib import Path

import pytest

from packs.bus import datos as horarios_datos
from packs.bus.tests.compat import Conv, MockWA, congelar, datos_reales

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def _instalados() -> dict[str, horarios_datos.Datos]:
    """Los datos que verá la conversación: los reales, salvo que un test pida
    unos sintéticos (`datos_motor`, `datos_pendientes`, `datos_muchas_lineas`),
    como hacía el `instalar()` global de buscaBus."""
    return {"datos": datos_reales()}


@pytest.fixture
def mock_wa() -> MockWA:
    return MockWA()


@pytest.fixture(params=["whatsapp", "telegram"])
def conv(
    request: pytest.FixtureRequest, mock_wa: MockWA, _instalados: dict[str, horarios_datos.Datos]
) -> Conv:
    """La conversación de buscaBus, en los dos tipos de canal."""
    c = Conv(mock_wa, request.param)
    c.instalados = _instalados
    return c


@pytest.fixture
def freeze_calendario(conv: Conv) -> Callable[..., None]:
    def _apply(fecha: date, hora: tuple[int, int] | None = None) -> None:
        congelar(conv, fecha, hora)

    return _apply


@pytest.fixture
def datos_motor(_instalados: dict[str, horarios_datos.Datos]) -> horarios_datos.Datos:
    """Los datos sintéticos de `fixtures/horarios_motor/`, para los casos borde
    que `horarios_real/` no cubre con comodidad (sin_datos, sin_servicio largo,
    a demanda, viernes lectivo, fusión)."""
    d = horarios_datos.cargar(
        FIXTURES / "horarios_motor", ["Pueblo A", "Pueblo E", "Pueblo K", "Pueblo N"]
    )
    _instalados["datos"] = d
    return d


@pytest.fixture
def datos_pendientes(_instalados: dict[str, horarios_datos.Datos]) -> horarios_datos.Datos:
    """Los datos sintéticos de `fixtures/horarios_pendientes/` (localidades
    pendientes, P15/P32)."""
    d = horarios_datos.cargar(FIXTURES / "horarios_pendientes", ["Pueblo A", "Pueblo B"])
    _instalados["datos"] = d
    return d


def crear_horarios_muchas_lineas(directorio: Path | str) -> None:
    """Genera un `horarios/` sintético para probar la paginación de la lista de
    líneas (P18): 12 líneas desde un mismo origen ("Origen"); "Linea Larga"
    pasa por 18 pueblos y "Ruta muy larga del norte al sur de la sierra" (más
    de 24 caracteres) lleva `nombre_corto: Ruta del norte`."""
    directorio = Path(directorio)
    (directorio / "lineas").mkdir(parents=True, exist_ok=True)

    def codigo(i: int) -> str:
        return f"{chr(65 + i // 26)}{chr(65 + i % 26)}Z"

    lineas: list[tuple[str, str, str | None, int]] = []
    for n in range(1, 11):
        lineas.append((f"linea-{n:02d}", f"Linea {n:02d}", None, 1))
    lineas.append(("linea-larga", "Linea Larga", None, 18))
    lineas.append(
        (
            "ruta-norte",
            "Ruta muy larga del norte al sur de la sierra",
            "Ruta del norte",
            2,
        )
    )
    localidades = ["  origen: { nombre: Origen }"]
    paradas = ["  ORI: { nombre: Origen, localidad: origen }"]
    contador = 0
    for lid, nombre, corto, n_pueblos in lineas:
        cabecera = ["ORI"]
        horas = ["08:00"]
        for k in range(n_pueblos):
            contador += 1
            pid = f"aldea-{contador:02d}"
            localidades.append(f"  {pid}: {{ nombre: Aldea {contador:02d} }}")
            paradas.append(
                f"  {codigo(contador)}: {{ nombre: Aldea {contador:02d}, localidad: {pid} }}"
            )
            cabecera.append(codigo(contador))
            horas.append(f"{8 + (k + 1) * 5 // 60:02d}:{(k + 1) * 5 % 60:02d}")
        texto = f"nombre: {nombre}\n"
        if corto:
            texto += f"nombre_corto: {corto}\n"
        texto += (
            "avisos: []\nno_circula: []\n\n"
            "temporadas:\n  anual: todo el año\n\n"
            "dias:\n  anual: { lunes-viernes: horario, sabado: sin_servicio, "
            "domingos-festivos: sin_servicio }\n\n"
            "horarios:\n  - temporada: anual\n    dias: lunes-viernes\n"
            "    tabla: |\n"
            f"      {'  '.join(cabecera)}\n"
            f"      {'  '.join(horas)}\n\n"
            "pendientes: []\n"
        )
        (directorio / "lineas" / f"{lid}.yaml").write_text(texto, encoding="utf-8")
    (directorio / "paradas.yaml").write_text(
        "localidades:\n" + "\n".join(localidades) + "\n\nparadas:\n" + "\n".join(paradas) + "\n",
        encoding="utf-8",
    )
    (directorio / "observaciones.yaml").write_text("{}\n", encoding="utf-8")
    (directorio / "calendario.yaml").write_text(
        "vigencia: 01/01/2026 - 31/08/2027\n\nfestivos:\n"
        "  01/01/2026: Año Nuevo\n\ncurso:\n  inicio_clases: 01/09/2026\n"
        "  fin_clases: 30/06/2027\n  vacaciones:\n"
        "    - 23/12/2026 - 07/01/2027\n  no_lectivos: []\n\npendientes: []\n",
        encoding="utf-8",
    )


@pytest.fixture
def datos_muchas_lineas(
    tmp_path: Path, _instalados: dict[str, horarios_datos.Datos]
) -> horarios_datos.Datos:
    """El `horarios/` sintético de `crear_horarios_muchas_lineas`."""
    crear_horarios_muchas_lineas(tmp_path)
    d = horarios_datos.cargar(tmp_path, ["Origen"])
    _instalados["datos"] = d
    return d


def crear_horarios_muchas_salidas(directorio: Path) -> None:
    """Un `horarios/` sintético con 228 salidas diarias de Origen a Destino (cada
    5 minutos de 05:00 a 23:55): su resultado pasa de 4.096 caracteres y se
    corta (design.md §10.3)."""
    (directorio / "lineas").mkdir(parents=True, exist_ok=True)
    (directorio / "paradas.yaml").write_text(
        "localidades:\n  origen: { nombre: Origen }\n  destino: { nombre: Destino }\n\n"
        "paradas:\n  ORI: { nombre: Origen, localidad: origen }\n"
        "  DES: { nombre: Destino, localidad: destino }\n",
        encoding="utf-8",
    )
    (directorio / "observaciones.yaml").write_text("{}\n", encoding="utf-8")
    (directorio / "calendario.yaml").write_text(
        "vigencia: 01/01/2026 - 31/08/2027\n\nfestivos:\n  01/01/2026: Año Nuevo\n\n"
        "curso:\n  inicio_clases: 01/09/2026\n  fin_clases: 30/06/2027\n"
        "  vacaciones: []\n  no_lectivos: []\n\npendientes: []\n",
        encoding="utf-8",
    )
    filas = []
    for i in range(228):
        salida = 5 * 60 + 5 * i
        llegada = salida + 55 if salida + 55 < 24 * 60 else 23 * 60 + 59
        filas.append(
            f"      {salida // 60:02d}:{salida % 60:02d}  {llegada // 60:02d}:{llegada % 60:02d}"
        )
    (directorio / "lineas" / "larga.yaml").write_text(
        "nombre: Línea larga\navisos: []\nno_circula: []\n\n"
        "temporadas:\n  anual: todo el año\n\n"
        "dias:\n  anual: { lunes-viernes: horario, sabado: sin_servicio,"
        " domingos-festivos: sin_servicio }\n\n"
        "horarios:\n  - temporada: anual\n    dias: lunes-viernes\n    tabla: |\n"
        "      ORI    DES\n" + "\n".join(filas) + "\n\npendientes: []\n",
        encoding="utf-8",
    )


@pytest.fixture
def datos_muchas_salidas(tmp_path: Path) -> horarios_datos.Datos:
    crear_horarios_muchas_salidas(tmp_path)
    return horarios_datos.cargar(tmp_path, ["Origen"])
