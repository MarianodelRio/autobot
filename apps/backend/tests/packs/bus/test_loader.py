"""packs/bus/tests/test_loader.py — cargar() nunca devuelve datos parciales: o carga
horarios/ con índices precalculados, o lanza HorariosInvalidos con la
lista completa de errores."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from packs.bus import formato, loader
from packs.bus.datos import Datos

FIXTURES = Path(__file__).parent / "fixtures"
HORARIOS_FICTICIOS = FIXTURES / "horarios_ficticios"


def test_cargar_horarios_ficticios() -> None:
    horarios = loader.cargar(HORARIOS_FICTICIOS)
    assert horarios.modelo is not None
    assert horarios.modelo.calendario is not None
    # Pozoluengo tiene dos paradas físicas (pueblo/hospital).
    assert set(horarios.localidad_paradas["pozoluengo"]) == {"POZ", "POH"}
    # Todo viaje que pare en alguna parada de Pozoluengo debe estar indexado.
    for viaje in horarios.localidad_viajes["pozoluengo"]:
        codigos_localidad = set(horarios.localidad_paradas["pozoluengo"])
        assert any(p.parada in codigos_localidad for p in viaje.pasos)


def test_cargar_directorio_invalido_lanza_horarios_invalidos(tmp_path: Path) -> None:
    horarios_dir = tmp_path / "horarios"
    (horarios_dir / "lineas").mkdir(parents=True)
    (horarios_dir / "paradas.yaml").write_text(
        (FIXTURES / "paradas_base.yaml").read_text(encoding="utf-8"), encoding="utf-8"
    )
    (horarios_dir / "observaciones.yaml").write_text(
        (FIXTURES / "observaciones_base.yaml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    # calendario.yaml ausente a propósito: horarios/ no valida.
    with pytest.raises(loader.HorariosInvalidos) as exc_info:
        loader.cargar(horarios_dir)
    assert any("calendario.yaml" in e for e in exc_info.value.errores)


def test_cargar_motor_fixture() -> None:
    horarios = loader.cargar(FIXTURES / "horarios_motor")
    assert "linea-viernes" in horarios.modelo.lineas
    assert set(horarios.localidad_paradas["pueblo-a"]) == {"AAA"}


def test_festivos_por_linea_ficticios_solo_la_linea_de_odalla() -> None:
    horarios = loader.cargar(HORARIOS_FICTICIOS)
    esperado = {
        date(2026, 10, 14): ("Fiesta local de Odalla", "odalla"),
        date(2026, 10, 16): ("Feria de Odalla", "odalla"),
    }
    assert set(horarios.festivos_por_linea) == {"riomayor-odalla"}
    assert horarios.festivos_por_linea["riomayor-odalla"] == esperado
    # Una línea que no toca Odalla no lleva festivos locales.
    assert "riomayor-ribazo" not in horarios.festivos_por_linea


def test_festivos_por_linea_solo_las_lineas_que_tocan_la_localidad() -> None:
    horarios = loader.cargar(FIXTURES / "horarios_festivo_local")
    assert set(horarios.festivos_por_linea) == {"linea-con-a", "linea-viernes-a"}
    assert horarios.festivos_por_linea["linea-con-a"][date(2026, 10, 14)] == (
        "Fiesta local de A",
        "pueblo-a",
    )


def test_festivos_locales_localidad_sin_lineas_avisa_sin_fallar() -> None:
    resultado = formato.validar(HORARIOS_FICTICIOS)
    assert resultado.errores == []
    assert not any("festivos_locales" in a for a in resultado.avisos)


# ── lineas_pueblos (P18) ─────────────────────────────────────────────────


def test_lineas_pueblos_ficticios_orden_y_contenido() -> None:
    horarios = loader.cargar(HORARIOS_FICTICIOS)
    lp = horarios.lineas_pueblos
    modelo = horarios.modelo
    # líneas en orden de título normalizado
    titulos = [formato.normalizar(modelo.lineas[lid].titulo) for lid in lp]
    assert titulos == sorted(titulos)
    assert list(lp)[:3] == [
        "pozoluengo-riomayor",
        "riomayor-fuenteclara",
        "riomayor-montealto",
    ]
    assert set(lp) == set(modelo.lineas)
    # pueblos en orden alfabético normalizado, sin columnas vacías
    for lid, ids in lp.items():
        assert ids, lid
        nombres = [formato.normalizar(modelo.localidades[i].nombre) for i in ids]
        assert nombres == sorted(nombres)
    assert lp["pozoluengo-riomayor"] == ("carrascal", "pozoluengo", "riomayor")
    assert lp["riomayor-pinarnuevo"] == ("campoalto", "pinarnuevo", "riomayor", "valdejunco")


def test_lineas_pueblos_fuenteclara_solo_en_riomayor_fuenteclara() -> None:
    horarios = loader.cargar(HORARIOS_FICTICIOS)
    con_fuenteclara = [lid for lid, ids in horarios.lineas_pueblos.items() if "fuenteclara" in ids]
    assert con_fuenteclara == ["riomayor-fuenteclara"]


def test_lineas_pueblos_excluye_localidades_pendientes() -> None:
    horarios = loader.cargar(FIXTURES / "horarios_pendientes")
    todos = {i for ids in horarios.lineas_pueblos.values() for i in ids}
    assert "aldea-a" not in todos and "aldea-b" not in todos
    assert "pueblo-a" in todos


def test_calcular_lineas_pueblos_coincide_con_cargar() -> None:
    horarios = loader.cargar(HORARIOS_FICTICIOS)
    assert loader.calcular_lineas_pueblos(horarios.modelo) == horarios.lineas_pueblos


def test_lineas_pueblos_ordena_por_titulo_no_por_nombre(datos_muchas_lineas: Datos) -> None:
    lp = datos_muchas_lineas.horarios.lineas_pueblos
    assert list(lp)[-2:] == ["linea-larga", "ruta-norte"]  # "Ruta del norte" al final
    assert len(lp["linea-larga"]) == 19


def test_lineas_pueblos_ficticios_pinarnuevo_comparte_linea_con_campoalto() -> None:
    horarios = loader.cargar(HORARIOS_FICTICIOS)
    pinarnuevo = horarios.lineas_pueblos["riomayor-pinarnuevo"]
    for loc in ("riomayor", "campoalto", "pinarnuevo"):
        assert loc in pinarnuevo


def test_horarios_ficticios_oda_con_nombre_con_coma() -> None:
    horarios = loader.cargar(HORARIOS_FICTICIOS)
    assert horarios.modelo.paradas["ODA"].nombre == "Odalla (cruce, gasolinera)"
