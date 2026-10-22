"""Fixtures del pack `bus`, portadas de `buscaBus/tests/conftest.py`. En buscaBus
instalaban los datos en un global; aquí los devuelven, porque el pack los recibe
en `ctx.data`."""

from __future__ import annotations

from pathlib import Path

import pytest

from packs.bus import datos as horarios_datos


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
def datos_muchas_lineas(tmp_path: Path) -> horarios_datos.Datos:
    """El `horarios/` sintético de `crear_horarios_muchas_lineas`."""
    crear_horarios_muchas_lineas(tmp_path)
    return horarios_datos.cargar(tmp_path, ["Origen"])
