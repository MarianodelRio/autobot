"""packs/bus/tests/test_calendario.py — calendario.py (lógica pura de calendario) y la
validación de calendario.yaml en formato.py."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from packs.bus import calendario, formato
from packs.bus.tests.helpers import calendario_de, modelo_de

FIXTURES = Path(__file__).parent / "fixtures"

HORARIOS_REAL = FIXTURES / "horarios_real"

_RESULTADO_REAL = formato.validar(HORARIOS_REAL)
CAL_REAL = calendario_de(_RESULTADO_REAL)


def test_horarios_real_valida_calendario_sin_errores() -> None:
    assert _RESULTADO_REAL.errores == []
    assert CAL_REAL is not None


def test_festivo_en_sabado_usa_clase_festivos() -> None:
    # 01/05/2027 (Fiesta del Trabajo) cae en sábado: el festivo gana siempre.
    info = calendario.info_dia(CAL_REAL, date(2027, 5, 1))
    assert info.clase_dia == "festivos"
    assert info.es_festivo is True


def test_festivo_en_lunes_usa_clase_festivos() -> None:
    # 12/10/2026 (Fiesta Nacional) cae en lunes.
    info = calendario.info_dia(CAL_REAL, date(2026, 10, 12))
    assert info.clase_dia == "festivos"
    assert info.es_festivo is True


def test_no_lectivo_declarado_no_es_lectivo_aunque_sea_viernes() -> None:
    # 26/02/2027 es viernes y está en `no_lectivos`.
    info = calendario.info_dia(CAL_REAL, date(2027, 2, 26))
    assert info.clase_dia == "viernes"
    assert info.dia_semana == "viernes"
    assert info.es_lectivo is False


def test_viernes_lectivo_dentro_de_curso() -> None:
    # 02/10/2026 es viernes, dentro de curso y sin vacaciones/festivo/no_lectivo.
    info = calendario.info_dia(CAL_REAL, date(2026, 10, 2))
    assert info.dia_semana == "viernes"
    assert info.es_lectivo is True


def test_antes_de_inicio_de_clases_no_es_lectivo() -> None:
    # 09/09/2026 es miércoles, anterior a inicio_clases (10/09/2026).
    info = calendario.info_dia(CAL_REAL, date(2026, 9, 9))
    assert info.es_lectivo is False


def test_festivos_marcados() -> None:
    for fecha in (date(2026, 12, 25), date(2027, 3, 26)):
        info = calendario.info_dia(CAL_REAL, fecha)
        assert info.es_festivo is True


def test_fecha_fuera_de_vigencia_lanza_excepcion() -> None:
    with pytest.raises(calendario.FueraDeCalendario):
        calendario.info_dia(CAL_REAL, date(2010, 1, 1))


def test_fecha_posterior_a_vigencia_2027_lanza_excepcion() -> None:
    # El curso 2027-28 no está cargado: no hay datos más allá del 31/08/2027.
    with pytest.raises(calendario.FueraDeCalendario):
        calendario.info_dia(CAL_REAL, date(2027, 10, 1))


def test_31_de_agosto_de_2027_dentro_de_vigencia() -> None:
    info = calendario.info_dia(CAL_REAL, date(2027, 8, 31))
    assert info.es_lectivo is False


def test_1_de_septiembre_de_2027_fuera_de_vigencia() -> None:
    with pytest.raises(calendario.FueraDeCalendario):
        calendario.info_dia(CAL_REAL, date(2027, 9, 1))


def test_vigencia_no_se_amplia_mas_alla_del_curso_cargado() -> None:
    # Protección contra volver a ensanchar vigencia_fin sin cargar el curso
    # siguiente (el bug corregido el 2026-09-27): vigencia_fin no puede caer
    # después del 31/08 del año escolar cuyo fin_clases ya conocemos.
    limite = date(CAL_REAL.fin_clases.year, 8, 31)
    assert CAL_REAL.vigencia_fin <= limite, (
        "vigencia_fin se ha ampliado más allá del 31/08 del curso cargado "
        "(fin_clases) sin haber cargado el curso escolar siguiente; esto "
        "reproduce el bug de 2026-09-27 (festivos de 2027-28 dados por "
        "buenos sin confirmación de negocio)."
    )


def test_temporada_de_pozoblanco_cambia_el_14_y_15_de_septiembre() -> None:
    linea = modelo_de(_RESULTADO_REAL).lineas["pozoblanco-cordoba"]
    t14 = calendario.temporada_de(linea, date(2026, 9, 14))
    t15 = calendario.temporada_de(linea, date(2026, 9, 15))
    assert t14 is not None and t15 is not None
    assert t14.nombre == "verano"
    assert t15.nombre == "invierno"
    assert t14.nombre != t15.nombre


def test_temporada_de_adamuz_cambia_el_31_de_agosto_y_1_de_septiembre() -> None:
    linea = modelo_de(_RESULTADO_REAL).lineas["adamuz-cordoba"]
    t31 = calendario.temporada_de(linea, date(2026, 8, 31))
    t1 = calendario.temporada_de(linea, date(2026, 9, 1))
    assert t31 is not None and t1 is not None
    assert t31.nombre == "verano"
    assert t1.nombre == "invierno"
    assert t31.nombre != t1.nombre


# ── Validación de calendario.yaml ───────────────────────────────────────────


def _build(tmp_path: Path, calendario_yaml: str) -> Path:
    horarios_dir = tmp_path / "horarios"
    (horarios_dir / "lineas").mkdir(parents=True)
    (horarios_dir / "paradas.yaml").write_text(
        (FIXTURES / "paradas_base.yaml").read_text(encoding="utf-8"), encoding="utf-8"
    )
    (horarios_dir / "observaciones.yaml").write_text(
        (FIXTURES / "observaciones_base.yaml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (horarios_dir / "calendario.yaml").write_text(calendario_yaml, encoding="utf-8")
    return horarios_dir


CALENDARIO_VALIDO = """\
vigencia: 01/01/2026 - 31/12/2026
festivos:
  01/01/2026: Año Nuevo
curso:
  inicio_clases: 10/09/2026
  fin_clases: 20/12/2026
  vacaciones: []
  no_lectivos: []
pendientes: []
"""


def test_calendario_yaml_ausente_es_error(tmp_path: Path) -> None:
    horarios_dir = tmp_path / "horarios"
    (horarios_dir / "lineas").mkdir(parents=True)
    (horarios_dir / "paradas.yaml").write_text(
        (FIXTURES / "paradas_base.yaml").read_text(encoding="utf-8"), encoding="utf-8"
    )
    (horarios_dir / "observaciones.yaml").write_text(
        (FIXTURES / "observaciones_base.yaml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    resultado = formato.validar(horarios_dir)
    assert any("calendario.yaml" in e for e in resultado.errores)


def test_calendario_fecha_invalida_es_error(tmp_path: Path) -> None:
    calendario_yaml = CALENDARIO_VALIDO.replace(
        "01/01/2026: Año Nuevo", "31/02/2026: Fecha imposible"
    )
    horarios_dir = _build(tmp_path, calendario_yaml)
    resultado = formato.validar(horarios_dir)
    assert any("festivo con fecha inválida" in e for e in resultado.errores)


def test_calendario_festivo_duplicado_es_error(tmp_path: Path) -> None:
    # Dos claves YAML distintas ("01/01/2026" y la misma con espacio inicial,
    # que el parser de fecha normaliza igual) que resuelven a la misma fecha:
    # una clave YAML repetida literal se colapsaría antes de llegar aquí.
    calendario_yaml = CALENDARIO_VALIDO.replace(
        "festivos:\n  01/01/2026: Año Nuevo",
        'festivos:\n  01/01/2026: Año Nuevo\n  " 01/01/2026": Repetido',
    )
    horarios_dir = _build(tmp_path, calendario_yaml)
    resultado = formato.validar(horarios_dir)
    assert any("festivo duplicado" in e for e in resultado.errores)


def test_calendario_festivo_fuera_de_vigencia_es_error(tmp_path: Path) -> None:
    calendario_yaml = CALENDARIO_VALIDO.replace(
        "01/01/2026: Año Nuevo", "01/01/2026: Año Nuevo\n  01/01/2028: Fuera de rango"
    )
    horarios_dir = _build(tmp_path, calendario_yaml)
    resultado = formato.validar(horarios_dir)
    assert any("fuera de la vigencia del calendario" in e for e in resultado.errores)


def test_calendario_rango_invertido_es_error(tmp_path: Path) -> None:
    calendario_yaml = CALENDARIO_VALIDO.replace(
        "vigencia: 01/01/2026 - 31/12/2026", "vigencia: 31/12/2026 - 01/01/2026"
    )
    horarios_dir = _build(tmp_path, calendario_yaml)
    resultado = formato.validar(horarios_dir)
    assert any("fecha de fin anterior a la de inicio" in e for e in resultado.errores)


def test_calendario_campo_desconocido_es_error(tmp_path: Path) -> None:
    calendario_yaml = CALENDARIO_VALIDO + "campo_raro: 1\n"
    horarios_dir = _build(tmp_path, calendario_yaml)
    resultado = formato.validar(horarios_dir)
    assert any("campo(s) desconocido(s)" in e for e in resultado.errores)


def test_calendario_inicio_clases_posterior_a_fin_es_error(tmp_path: Path) -> None:
    calendario_yaml = CALENDARIO_VALIDO.replace(
        "inicio_clases: 10/09/2026\n  fin_clases: 20/12/2026",
        "inicio_clases: 20/12/2026\n  fin_clases: 10/09/2026",
    )
    horarios_dir = _build(tmp_path, calendario_yaml)
    resultado = formato.validar(horarios_dir)
    assert any("es posterior a 'curso.fin_clases'" in e for e in resultado.errores)


def test_calendario_curso_no_es_mapa_es_error(tmp_path: Path) -> None:
    calendario_yaml = CALENDARIO_VALIDO.replace(
        "curso:\n  inicio_clases: 10/09/2026\n  fin_clases: 20/12/2026\n"
        "  vacaciones: []\n  no_lectivos: []\n",
        "curso: no es un mapa\n",
    )
    horarios_dir = _build(tmp_path, calendario_yaml)
    resultado = formato.validar(horarios_dir)
    assert any("'curso' debe ser un mapa" in e for e in resultado.errores)


def test_calendario_curso_sin_campo_obligatorio_es_error(tmp_path: Path) -> None:
    calendario_yaml = CALENDARIO_VALIDO.replace("  inicio_clases: 10/09/2026\n", "")
    horarios_dir = _build(tmp_path, calendario_yaml)
    resultado = formato.validar(horarios_dir)
    assert any(
        "'curso' no define campo(s) obligatorio(s)" in e and "inicio_clases" in e
        for e in resultado.errores
    )


def test_calendario_pendiente_malformado_es_error(tmp_path: Path) -> None:
    calendario_yaml = CALENDARIO_VALIDO.replace("pendientes: []", "pendientes: [P3]")
    horarios_dir = _build(tmp_path, calendario_yaml)
    resultado = formato.validar(horarios_dir)
    assert any("pendiente inválido 'P3'" in e for e in resultado.errores)


def test_calendario_pendiente_valido_avisa(tmp_path: Path) -> None:
    calendario_yaml = CALENDARIO_VALIDO.replace("pendientes: []", "pendientes: [P03]")
    horarios_dir = _build(tmp_path, calendario_yaml)
    resultado = formato.validar(horarios_dir)
    assert resultado.errores == []
    assert any("pendiente P03" in a for a in resultado.avisos)


# ── sin_servicio_todas_las_lineas (P03g) ────────────────────────────────────


def test_calendario_real_declara_sin_servicio_25_12_y_01_01() -> None:
    assert CAL_REAL.sin_servicio_todas_las_lineas == frozenset({(12, 25), (1, 1)})
    # ambas fechas siguen en festivos (nombre del festivo para la cabecera)
    assert date(2026, 12, 25) in CAL_REAL.festivos
    assert date(2027, 1, 1) in CAL_REAL.festivos


def test_info_dia_fuera_de_vigencia_permitido_da_nombre_none() -> None:
    info = calendario.info_dia(CAL_REAL, date(2027, 12, 25), permitir_fuera_de_vigencia=True)
    assert info.nombre_festivo is None
    assert info.es_festivo is False
    assert info.dia_semana == "sabado"


def test_sin_servicio_todas_las_lineas_valido_incluye_29_02(tmp_path: Path) -> None:
    calendario_yaml = CALENDARIO_VALIDO + "sin_servicio_todas_las_lineas: [25/12, 29/02]\n"
    resultado = formato.validar(_build(tmp_path, calendario_yaml))
    assert resultado.errores == []
    assert calendario_de(resultado).sin_servicio_todas_las_lineas == frozenset({(12, 25), (2, 29)})


def test_sin_servicio_todas_las_lineas_31_02_es_error(tmp_path: Path) -> None:
    calendario_yaml = CALENDARIO_VALIDO + "sin_servicio_todas_las_lineas: [31/02]\n"
    resultado = formato.validar(_build(tmp_path, calendario_yaml))
    assert any(
        "calendario.yaml" in e and "sin_servicio_todas_las_lineas" in e and "31/02" in e
        for e in resultado.errores
    )


def test_sin_servicio_todas_las_lineas_formato_invalido_es_error(tmp_path: Path) -> None:
    calendario_yaml = CALENDARIO_VALIDO + "sin_servicio_todas_las_lineas: [25/12/2026]\n"
    resultado = formato.validar(_build(tmp_path, calendario_yaml))
    assert any("fecha inválida '25/12/2026'" in e for e in resultado.errores)


def test_sin_servicio_todas_las_lineas_repetida_es_error(tmp_path: Path) -> None:
    calendario_yaml = CALENDARIO_VALIDO + "sin_servicio_todas_las_lineas: [25/12, 25/12]\n"
    resultado = formato.validar(_build(tmp_path, calendario_yaml))
    assert any("fecha repetida '25/12'" in e for e in resultado.errores)


def test_sin_servicio_todas_las_lineas_no_es_lista_es_error(tmp_path: Path) -> None:
    calendario_yaml = CALENDARIO_VALIDO + "sin_servicio_todas_las_lineas: 25/12\n"
    resultado = formato.validar(_build(tmp_path, calendario_yaml))
    assert any("debe ser una lista" in e for e in resultado.errores)


def test_calendario_campo_desconocido_cercano_es_error(tmp_path: Path) -> None:
    calendario_yaml = CALENDARIO_VALIDO + "sin_servicio_todas_lineas: [25/12]\n"
    resultado = formato.validar(_build(tmp_path, calendario_yaml))
    assert any(
        "campo(s) desconocido(s)" in e and "sin_servicio_todas_lineas" in e
        for e in resultado.errores
    )


# ── Festivos locales por línea (P03e) ───────────────────────────────────────


def test_calendario_real_declara_festivos_locales_de_cordoba() -> None:
    assert CAL_REAL.festivos_locales == {
        "cordoba": {
            date(2026, 9, 8): "Virgen de la Fuensanta",
            date(2026, 10, 24): "San Rafael",
        }
    }


def test_clase_dia_linea_sin_festivo_local_es_la_del_dia() -> None:
    info = calendario.info_dia(CAL_REAL, date(2026, 9, 30))  # miércoles
    assert calendario.clase_dia_linea(info, {}) == ("miercoles", None)
    otro = {date(2026, 10, 24): ("San Rafael", "cordoba")}
    assert calendario.clase_dia_linea(info, otro) == ("miercoles", None)


def test_clase_dia_linea_con_festivo_local_usa_festivos_aunque_sea_sabado() -> None:
    # 24/10/2026 es sábado y festivo local de Córdoba.
    info = calendario.info_dia(CAL_REAL, date(2026, 10, 24))
    assert info.clase_dia == "sabado"
    assert info.es_festivo is False
    locales = {date(2026, 10, 24): ("San Rafael", "cordoba")}
    assert calendario.clase_dia_linea(info, locales) == (
        "festivos",
        ("San Rafael", "cordoba"),
    )
    # InfoDia no cambia por un festivo local (P04)
    assert info.es_lectivo is False


def test_clase_dia_linea_local_no_cambia_es_lectivo() -> None:
    # 08/09/2026 es martes, antes de inicio de clases: no lectivo; el festivo
    # local no altera InfoDia.
    info = calendario.info_dia(CAL_REAL, date(2026, 9, 8))
    assert info.es_lectivo is False and info.clase_dia == "martes"


def test_clase_dia_linea_con_festivo_general_y_local_devuelve_ambos() -> None:
    info = calendario.info_dia(CAL_REAL, date(2026, 12, 25))
    locales = {date(2026, 12, 25): ("Fiesta local", "cordoba")}
    clase, local = calendario.clase_dia_linea(info, locales)
    assert clase == "festivos"
    assert local == ("Fiesta local", "cordoba")
    # y solo con el general: sin festivo local
    assert calendario.clase_dia_linea(info, {}) == ("festivos", None)


FESTIVOS_LOCALES_BASE = (
    CALENDARIO_VALIDO + "festivos_locales:\n  pueblo-a:\n    10/10/2026: Fiesta de A\n"
)


def test_festivos_locales_validos(tmp_path: Path) -> None:
    resultado = formato.validar(_build(tmp_path, FESTIVOS_LOCALES_BASE))
    assert resultado.errores == []
    assert calendario_de(resultado).festivos_locales == {
        "pueblo-a": {date(2026, 10, 10): "Fiesta de A"}
    }


def test_festivos_locales_localidad_desconocida_es_error(tmp_path: Path) -> None:
    yaml_ = FESTIVOS_LOCALES_BASE.replace("pueblo-a:", "pueblo-zzz:")
    resultado = formato.validar(_build(tmp_path, yaml_))
    assert any(
        "festivos_locales" in e and "localidad sin definir ('pueblo-zzz')" in e
        for e in resultado.errores
    )


def test_festivos_locales_fecha_fuera_de_vigencia_es_error(tmp_path: Path) -> None:
    yaml_ = FESTIVOS_LOCALES_BASE.replace("10/10/2026", "10/10/2028")
    resultado = formato.validar(_build(tmp_path, yaml_))
    assert any(
        "festivo local" in e and "fuera de la vigencia del calendario" in e
        for e in resultado.errores
    )


def test_festivos_locales_fecha_repetida_en_la_localidad_es_error(tmp_path: Path) -> None:
    yaml_ = FESTIVOS_LOCALES_BASE + '    " 10/10/2026": Repetido\n'
    resultado = formato.validar(_build(tmp_path, yaml_))
    assert any("con fecha repetida" in e and "pueblo-a" in e for e in resultado.errores)


def test_festivos_locales_fecha_ya_en_festivos_generales_es_error(tmp_path: Path) -> None:
    yaml_ = FESTIVOS_LOCALES_BASE.replace("10/10/2026", "01/01/2026")
    resultado = formato.validar(_build(tmp_path, yaml_))
    assert any("ya está en 'festivos'" in e and "01/01/2026" in e for e in resultado.errores)


def test_festivos_locales_fecha_invalida_es_error(tmp_path: Path) -> None:
    yaml_ = FESTIVOS_LOCALES_BASE.replace("10/10/2026", "31/02/2026")
    resultado = formato.validar(_build(tmp_path, yaml_))
    assert any("fecha inválida '31/02/2026'" in e for e in resultado.errores)


def test_festivos_locales_localidad_sin_lineas_avisa(tmp_path: Path) -> None:
    # _build no crea líneas: pueblo-a existe pero ninguna línea la usa.
    resultado = formato.validar(_build(tmp_path, FESTIVOS_LOCALES_BASE))
    assert resultado.errores == []
    assert any(
        "festivos_locales" in a and "pueblo-a" in a and "ninguna línea" in a
        for a in resultado.avisos
    )
