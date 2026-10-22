"""packs/bus/tests/test_loader.py — cargar() nunca devuelve datos parciales: o carga
horarios/ real con índices precalculados, o lanza HorariosInvalidos con la
lista completa de errores (buscaBus/design.md, 2.4)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from packs.bus import formato, loader
from packs.bus.datos import Datos

FIXTURES = Path(__file__).parent / "fixtures"
HORARIOS_REAL = FIXTURES / "horarios_real"


def test_cargar_horarios_real() -> None:
    horarios = loader.cargar(HORARIOS_REAL)
    assert horarios.modelo is not None
    assert horarios.modelo.calendario is not None
    # Pozoblanco tiene dos paradas físicas (pueblo/hospital, P10).
    assert set(horarios.localidad_paradas["pozoblanco"]) == {"POZ", "PZH"}
    # Todo viaje que pare en alguna parada de Pozoblanco debe estar indexado.
    for viaje in horarios.localidad_viajes["pozoblanco"]:
        codigos_localidad = set(horarios.localidad_paradas["pozoblanco"])
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


def test_festivos_por_linea_real_las_10_lineas_que_tocan_cordoba() -> None:
    horarios = loader.cargar(HORARIOS_REAL)
    esperado = {
        date(2026, 9, 8): ("Virgen de la Fuensanta", "cordoba"),
        date(2026, 10, 24): ("San Rafael", "cordoba"),
    }
    sin_cordoba = {
        "belalcazar-pozoblanco",
        "torrecampo-pozoblanco",
        "santa-eufemia-villaralto-pozoblanco",
        "cardena-pozoblanco",
        "pozoblanco-estacion-ave",
    }
    assert set(horarios.modelo.lineas) >= sin_cordoba
    assert set(horarios.festivos_por_linea) == set(horarios.modelo.lineas) - sin_cordoba
    assert len(horarios.festivos_por_linea) == 10
    assert {"fuente-carreteros-cordoba", "villaviciosa-cordoba"} <= set(horarios.festivos_por_linea)
    for lid, festivos in horarios.festivos_por_linea.items():
        assert festivos == esperado, lid


def test_festivos_por_linea_solo_las_lineas_que_tocan_la_localidad() -> None:
    horarios = loader.cargar(FIXTURES / "horarios_festivo_local")
    assert set(horarios.festivos_por_linea) == {"linea-con-a", "linea-viernes-a"}
    assert horarios.festivos_por_linea["linea-con-a"][date(2026, 10, 14)] == (
        "Fiesta local de A",
        "pueblo-a",
    )


def test_festivos_locales_localidad_sin_lineas_avisa_sin_fallar() -> None:
    resultado = formato.validar(HORARIOS_REAL)
    assert resultado.errores == []
    assert not any("festivos_locales" in a for a in resultado.avisos)


# ── lineas_pueblos (P18) ─────────────────────────────────────────────────


def test_lineas_pueblos_real_orden_y_contenido() -> None:
    horarios = loader.cargar(HORARIOS_REAL)
    lp = horarios.lineas_pueblos
    modelo = horarios.modelo
    # líneas en orden de título normalizado
    titulos = [formato.normalizar(modelo.lineas[lid].titulo) for lid in lp]
    assert titulos == sorted(titulos)
    assert list(lp)[:3] == [
        "adamuz-cordoba",
        "badajoz-cordoba",
        "belalcazar-cordoba",
    ]
    assert set(lp) == set(modelo.lineas)
    # pueblos en orden alfabético normalizado, sin columnas vacías
    for lid, ids in lp.items():
        assert ids, lid
        nombres = [formato.normalizar(modelo.localidades[i].nombre) for i in ids]
        assert nombres == sorted(nombres)
    assert lp["adamuz-cordoba"] == (
        "adamuz",
        "alcolea",
        "algallarin",
        "aquasierra",
        "campus-de-rabanales",
        "cordoba",
        "villafranca-de-cordoba",
    )
    assert lp["villaviciosa-cordoba"] == (
        "cordoba",
        "pantano",
        "el-vacar",
        "villaviciosa-de-cordoba",
    )


def test_lineas_pueblos_cabeza_del_buey_solo_en_belalcazar_cordoba() -> None:
    horarios = loader.cargar(HORARIOS_REAL)
    con_cabeza = [lid for lid, ids in horarios.lineas_pueblos.items() if "cabeza-del-buey" in ids]
    assert con_cabeza == ["belalcazar-cordoba"]


def test_lineas_pueblos_excluye_localidades_pendientes() -> None:
    horarios = loader.cargar(FIXTURES / "horarios_pendientes")
    todos = {i for ids in horarios.lineas_pueblos.values() for i in ids}
    assert "aldea-a" not in todos and "aldea-b" not in todos
    assert "pueblo-a" in todos


def test_calcular_lineas_pueblos_coincide_con_cargar() -> None:
    horarios = loader.cargar(HORARIOS_REAL)
    assert loader.calcular_lineas_pueblos(horarios.modelo) == horarios.lineas_pueblos


def test_lineas_pueblos_ordena_por_titulo_no_por_nombre(datos_muchas_lineas: Datos) -> None:
    lp = datos_muchas_lineas.horarios.lineas_pueblos
    assert list(lp)[-2:] == ["linea-larga", "ruta-norte"]  # "Ruta del norte" al final
    assert len(lp["linea-larga"]) == 19


def test_lineas_pueblos_real_los_blazquez_y_rivero_y_mochos_en_hornachuelos() -> None:
    horarios = loader.cargar(HORARIOS_REAL)
    blazquez = horarios.lineas_pueblos["los-blazquez"]
    for loc in ("el-porvenir", "la-granjuela", "valsequillo", "los-blazquez"):
        assert loc in blazquez
    # P32 cerrada el 07/10/2026: Rivero y Los Mochos son pueblos normales.
    hornachuelos = horarios.lineas_pueblos["hornachuelos-cordoba"]
    assert "rivero-de-posadas" in hornachuelos
    assert "los-mochos" in hornachuelos


def test_horarios_real_vrc_con_nombre_con_coma() -> None:
    horarios = loader.cargar(HORARIOS_REAL)
    assert horarios.modelo.paradas["VRC"].nombre == "Villanueva del Rey (cruce, gasolinera)"
