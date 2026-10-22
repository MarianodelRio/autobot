"""packs/bus/tests/test_formato.py — cada regla de buscaBus/design.md 2.3 rechaza su caso con un
mensaje concreto; horarios/ real valida sin errores."""

from __future__ import annotations

import shutil
from collections.abc import Sequence
from pathlib import Path

import pytest

from packs.bus import formato
from packs.bus.tests.helpers import modelo_de

FIXTURES = Path(__file__).parent / "fixtures"

HORARIOS_REAL = FIXTURES / "horarios_real"


def _build(
    tmp_path: Path,
    linea_yaml: str,
    paradas_fixture: str = "paradas_base.yaml",
    observaciones_fixture: str = "observaciones_base.yaml",
    linea_nombre: str = "linea-prueba",
    calendario_fixture: str = "calendario_base.yaml",
) -> Path:
    horarios_dir = tmp_path / "horarios"
    (horarios_dir / "lineas").mkdir(parents=True)
    (horarios_dir / "paradas.yaml").write_text(
        (FIXTURES / paradas_fixture).read_text(encoding="utf-8"), encoding="utf-8"
    )
    (horarios_dir / "observaciones.yaml").write_text(
        (FIXTURES / observaciones_fixture).read_text(encoding="utf-8"), encoding="utf-8"
    )
    (horarios_dir / "calendario.yaml").write_text(
        (FIXTURES / calendario_fixture).read_text(encoding="utf-8"), encoding="utf-8"
    )
    (horarios_dir / "lineas" / f"{linea_nombre}.yaml").write_text(linea_yaml, encoding="utf-8")
    return horarios_dir


BASE_VALIDA = """\
nombre: Línea de prueba
avisos: []
no_circula: []
temporadas:
  anual: todo el año
dias:
  anual:
    lunes-viernes: horario
    sabado: sin_servicio
    domingos-festivos: sin_servicio
horarios:
  - temporada: anual
    dias: lunes-viernes
    tabla: |
      AAA    BBB    CCC
      {fila}
pendientes: []
"""


def test_yaml_mal_formado(tmp_path: Path) -> None:
    horarios_dir = tmp_path / "horarios"
    (horarios_dir / "lineas").mkdir(parents=True)
    (horarios_dir / "paradas.yaml").write_text(
        (FIXTURES / "paradas_base.yaml").read_text(encoding="utf-8"), encoding="utf-8"
    )
    (horarios_dir / "observaciones.yaml").write_text(
        (FIXTURES / "observaciones_base.yaml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (horarios_dir / "calendario.yaml").write_text(
        (FIXTURES / "calendario_base.yaml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (horarios_dir / "lineas" / "mala.yaml").write_text("nombre: [sin cerrar\n", encoding="utf-8")

    resultado = formato.validar(horarios_dir)
    assert resultado.modelo is None
    assert any("YAML mal formado" in e for e in resultado.errores)


def test_campo_obligatorio_ausente(tmp_path: Path) -> None:
    linea = """\
nombre: Línea de prueba
temporadas:
  anual: todo el año
"""
    horarios_dir = _build(tmp_path, linea)
    resultado = formato.validar(horarios_dir)
    assert any("falta(n) campo(s) obligatorio(s)" in e for e in resultado.errores)


def test_codigo_parada_sin_definir(tmp_path: Path) -> None:
    linea = BASE_VALIDA.format(fila="08:00  08:10  -").replace("CCC", "ZZZ")
    horarios_dir = _build(tmp_path, linea)
    resultado = formato.validar(horarios_dir)
    assert any("código de parada sin definir 'ZZZ'" in e for e in resultado.errores)


def test_letra_de_observacion_sin_definir(tmp_path: Path) -> None:
    linea = BASE_VALIDA.format(fila="08:00Q  08:10  08:20")
    horarios_dir = _build(tmp_path, linea)
    resultado = formato.validar(horarios_dir)
    assert any("letra de observación sin definir 'Q'" in e for e in resultado.errores)


def test_observacion_en_ambito_no_permitido(tmp_path: Path) -> None:
    # entra_en_pueblo solo permite ámbito 'parada'; aquí se usa como
    # observación de viaje.
    linea = BASE_VALIDA.format(fila="08:00  08:10  08:20 | entra_en_pueblo")
    horarios_dir = _build(tmp_path, linea)
    resultado = formato.validar(horarios_dir)
    assert any("ámbito 'viaje' pero no lo permite" in e for e in resultado.errores)


def test_condicion_que_el_motor_no_sabe_aplicar(tmp_path: Path) -> None:
    linea = BASE_VALIDA.format(fila="08:00X  08:10  08:20")
    horarios_dir = _build(
        tmp_path,
        linea,
        observaciones_fixture="observaciones_condicion_desconocida.yaml",
    )
    resultado = formato.validar(horarios_dir)
    assert any("condición que el motor no sabe aplicar" in e for e in resultado.errores)


def test_fila_con_numero_de_valores_distinto(tmp_path: Path) -> None:
    linea = BASE_VALIDA.format(fila="08:00  08:10")
    horarios_dir = _build(tmp_path, linea)
    resultado = formato.validar(horarios_dir)
    assert any("2 valores, se esperaban 3" in e for e in resultado.errores)


def test_horas_que_retroceden(tmp_path: Path) -> None:
    linea = BASE_VALIDA.format(fila="08:00  07:50  09:00")
    horarios_dir = _build(tmp_path, linea)
    resultado = formato.validar(horarios_dir)
    assert any("las horas retroceden" in e for e in resultado.errores)


def test_viaje_con_menos_de_2_horas(tmp_path: Path) -> None:
    linea = BASE_VALIDA.format(fila="08:00  -  -")
    horarios_dir = _build(tmp_path, linea)
    resultado = formato.validar(horarios_dir)
    assert any("menos de 2 horas" in e for e in resultado.errores)


def test_temporadas_que_dejan_dias_sin_cubrir(tmp_path: Path) -> None:
    linea = """\
nombre: Línea de prueba
temporadas:
  invierno: 01/01 - 30/06
dias:
  invierno:
    lunes-viernes: horario
    sabado: sin_servicio
    domingos-festivos: sin_servicio
horarios:
  - temporada: invierno
    dias: lunes-viernes
    tabla: |
      AAA    BBB    CCC
      08:00  08:10  08:20
"""
    horarios_dir = _build(tmp_path, linea)
    resultado = formato.validar(horarios_dir)
    assert any("día(s) del año sin cubrir" in e for e in resultado.errores)


def test_temporadas_que_se_solapan(tmp_path: Path) -> None:
    linea = """\
nombre: Línea de prueba
temporadas:
  invierno: 01/01 - 31/12
  verano: 01/06 - 31/08
dias:
  invierno:
    lunes-viernes: horario
    sabado: sin_servicio
    domingos-festivos: sin_servicio
  verano:
    lunes-viernes: horario
    sabado: sin_servicio
    domingos-festivos: sin_servicio
horarios:
  - temporada: invierno
    dias: lunes-viernes
    tabla: |
      AAA    BBB    CCC
      08:00  08:10  08:20
  - temporada: verano
    dias: lunes-viernes
    tabla: |
      AAA    BBB    CCC
      08:00  08:10  08:20
"""
    horarios_dir = _build(tmp_path, linea)
    resultado = formato.validar(horarios_dir)
    assert any("se solapan" in e for e in resultado.errores)


def test_clase_de_dia_sin_declarar(tmp_path: Path) -> None:
    linea = """\
nombre: Línea de prueba
temporadas:
  anual: todo el año
dias:
  anual:
    lunes-viernes: horario
    sabado: sin_servicio
horarios:
  - temporada: anual
    dias: lunes-viernes
    tabla: |
      AAA    BBB    CCC
      08:00  08:10  08:20
"""
    horarios_dir = _build(tmp_path, linea)
    resultado = formato.validar(horarios_dir)
    assert any("sin declarar" in e for e in resultado.errores)


def test_clase_de_dia_declarada_dos_veces(tmp_path: Path) -> None:
    linea = """\
nombre: Línea de prueba
temporadas:
  anual: todo el año
dias:
  anual:
    lunes-viernes: horario
    viernes: horario
    sabado: sin_servicio
    domingos-festivos: sin_servicio
horarios:
  - temporada: anual
    dias: lunes-viernes
    tabla: |
      AAA    BBB    CCC
      08:00  08:10  08:20
"""
    horarios_dir = _build(tmp_path, linea)
    resultado = formato.validar(horarios_dir)
    assert any("declaradas dos veces" in e for e in resultado.errores)


def test_horario_sin_tabla(tmp_path: Path) -> None:
    linea = """\
nombre: Línea de prueba
temporadas:
  anual: todo el año
dias:
  anual:
    lunes-viernes: horario
    sabado: horario
    domingos-festivos: sin_servicio
horarios:
  - temporada: anual
    dias: lunes-viernes
    tabla: |
      AAA    BBB    CCC
      08:00  08:10  08:20
"""
    horarios_dir = _build(tmp_path, linea)
    resultado = formato.validar(horarios_dir)
    assert any("estado 'horario' sin" in e for e in resultado.errores)


def test_a_demanda_sin_telefono_demanda(tmp_path: Path) -> None:
    linea = BASE_VALIDA.format(fila="08:00D  08:10  08:20")
    horarios_dir = _build(tmp_path, linea)
    resultado = formato.validar(horarios_dir)
    assert any("no define 'telefono_demanda'" in e for e in resultado.errores)


def test_alias_no_es_lista_es_error(tmp_path: Path) -> None:
    horarios_dir = _build(tmp_path, BASE_VALIDA.format(fila="08:00  08:10  08:20"))
    paradas = """\
localidades:
  pueblo-a: { nombre: Pueblo A, alias: "no-es-lista" }
  pueblo-b: { nombre: Pueblo B }
  pueblo-c: { nombre: Pueblo C }
paradas:
  AAA: { nombre: Pueblo A, localidad: pueblo-a }
  BBB: { nombre: Pueblo B, localidad: pueblo-b }
  CCC: { nombre: Pueblo C, localidad: pueblo-c }
"""
    (horarios_dir / "paradas.yaml").write_text(paradas, encoding="utf-8")
    resultado = formato.validar(horarios_dir)
    assert any("'alias' debe ser una lista de cadenas" in e for e in resultado.errores)


def test_alias_vacio_al_normalizar_es_error(tmp_path: Path) -> None:
    horarios_dir = _build(tmp_path, BASE_VALIDA.format(fila="08:00  08:10  08:20"))
    paradas = """\
localidades:
  pueblo-a: { nombre: Pueblo A, alias: ["La"] }
  pueblo-b: { nombre: Pueblo B }
  pueblo-c: { nombre: Pueblo C }
paradas:
  AAA: { nombre: Pueblo A, localidad: pueblo-a }
  BBB: { nombre: Pueblo B, localidad: pueblo-b }
  CCC: { nombre: Pueblo C, localidad: pueblo-c }
"""
    (horarios_dir / "paradas.yaml").write_text(paradas, encoding="utf-8")
    resultado = formato.validar(horarios_dir)
    assert any("normaliza a una cadena vacía" in e for e in resultado.errores)


def test_alias_duplicado_en_la_misma_localidad_es_error(tmp_path: Path) -> None:
    horarios_dir = _build(tmp_path, BASE_VALIDA.format(fila="08:00  08:10  08:20"))
    paradas = """\
localidades:
  pueblo-a: { nombre: Pueblo A, alias: ["El Ache", "ache"] }
  pueblo-b: { nombre: Pueblo B }
  pueblo-c: { nombre: Pueblo C }
paradas:
  AAA: { nombre: Pueblo A, localidad: pueblo-a }
  BBB: { nombre: Pueblo B, localidad: pueblo-b }
  CCC: { nombre: Pueblo C, localidad: pueblo-c }
"""
    (horarios_dir / "paradas.yaml").write_text(paradas, encoding="utf-8")
    resultado = formato.validar(horarios_dir)
    assert any("está repetido" in e for e in resultado.errores)


def test_alias_igual_al_propio_nombre_es_error(tmp_path: Path) -> None:
    horarios_dir = _build(tmp_path, BASE_VALIDA.format(fila="08:00  08:10  08:20"))
    paradas = """\
localidades:
  pueblo-a: { nombre: Pueblo A, alias: ["pueblo a"] }
  pueblo-b: { nombre: Pueblo B }
  pueblo-c: { nombre: Pueblo C }
paradas:
  AAA: { nombre: Pueblo A, localidad: pueblo-a }
  BBB: { nombre: Pueblo B, localidad: pueblo-b }
  CCC: { nombre: Pueblo C, localidad: pueblo-c }
"""
    (horarios_dir / "paradas.yaml").write_text(paradas, encoding="utf-8")
    resultado = formato.validar(horarios_dir)
    assert any("coincide con el propio nombre de la localidad" in e for e in resultado.errores)


def test_dos_localidades_mismo_nombre_normalizado_es_error(tmp_path: Path) -> None:
    horarios_dir = _build(tmp_path, BASE_VALIDA.format(fila="08:00  08:10  08:20"))
    paradas = """\
localidades:
  pueblo-a: { nombre: "Pueblo A" }
  pueblo-a2: { nombre: "Pueblo, A" }
  pueblo-c: { nombre: Pueblo C }
paradas:
  AAA: { nombre: Pueblo A, localidad: pueblo-a }
  BBB: { nombre: Pueblo B, localidad: pueblo-a2 }
  CCC: { nombre: Pueblo C, localidad: pueblo-c }
"""
    (horarios_dir / "paradas.yaml").write_text(paradas, encoding="utf-8")
    resultado = formato.validar(horarios_dir)
    assert any("tienen el mismo nombre normalizado" in e for e in resultado.errores)


def test_parada_coincide_con_nombre_de_otra_localidad_es_error(tmp_path: Path) -> None:
    horarios_dir = _build(tmp_path, BASE_VALIDA.format(fila="08:00  08:10  08:20"))
    paradas = """\
localidades:
  pueblo-a: { nombre: Pueblo A }
  pueblo-b: { nombre: Pueblo B }
  pueblo-c: { nombre: Pueblo C }
paradas:
  AAA: { nombre: Pueblo A, localidad: pueblo-a }
  BBB: { nombre: "Pueblo B", localidad: pueblo-c }
  CCC: { nombre: Pueblo C, localidad: pueblo-c }
"""
    (horarios_dir / "paradas.yaml").write_text(paradas, encoding="utf-8")
    resultado = formato.validar(horarios_dir)
    assert any("coincide con el nombre de la localidad" in e for e in resultado.errores)


def test_horarios_real_avisa_ambiguedad_villafranca() -> None:
    resultado = formato.validar(HORARIOS_REAL)
    assert resultado.errores == []
    avisos_villafranca = [a for a in resultado.avisos if "villafranca" in a]
    assert len(avisos_villafranca) == 1
    assert "villafranca-de-cordoba" in avisos_villafranca[0]
    assert "villafranca-de-los-barros" in avisos_villafranca[0]


def test_horarios_real_valida_sin_errores() -> None:
    resultado = formato.validar(HORARIOS_REAL)
    assert resultado.errores == []
    assert resultado.modelo is not None


def test_horarios_real_avisa_de_pendientes_y_sin_datos() -> None:
    resultado = formato.validar(HORARIOS_REAL)
    assert any("pendiente" in a for a in resultado.avisos)


def test_localidad_sin_usar_avisa(tmp_path: Path) -> None:
    # paradas_base.yaml define tres localidades (pueblo-a/b/c); la línea de
    # prueba solo usa las paradas AAA y BBB, así que pueblo-c debe salir en el
    # aviso aunque su parada CCC ya salga en el de paradas sin usar.
    linea = """\
nombre: Línea de prueba
temporadas:
  anual: todo el año
dias:
  anual:
    lunes-viernes: horario
    sabado: sin_servicio
    domingos-festivos: sin_servicio
horarios:
  - temporada: anual
    dias: lunes-viernes
    tabla: |
      AAA    BBB
      08:00  08:10
"""
    horarios_dir = _build(tmp_path, linea)
    resultado = formato.validar(horarios_dir)
    assert resultado.errores == []
    assert any(
        "Localidades definidas que ninguna línea usa" in a and "pueblo-c" in a
        for a in resultado.avisos
    )
    assert any(
        "Paradas definidas que ninguna línea usa" in a and "CCC" in a for a in resultado.avisos
    )


def test_dos_tablas_con_mismos_extremos_es_error(tmp_path: Path) -> None:
    # Dos tablas con la misma temporada, días y extremos de cabecera (aquí,
    # las dos AAA -> CCC) son indistinguibles para el diff y la revisión.
    linea = """\
nombre: Línea de prueba
temporadas:
  anual: todo el año
dias:
  anual:
    lunes-viernes: horario
    sabado: sin_servicio
    domingos-festivos: sin_servicio
horarios:
  - temporada: anual
    dias: lunes-viernes
    tabla: |
      AAA    BBB    CCC
      08:00  08:10  08:20
  - temporada: anual
    dias: lunes-viernes
    tabla: |
      AAA    CCC
      09:00  09:20
"""
    horarios_dir = _build(tmp_path, linea)
    resultado = formato.validar(horarios_dir)
    assert any(
        "tablas con temporada 'anual', días 'lunes-viernes', de 'AAA' a 'CCC'" in e
        for e in resultado.errores
    )


def test_paradas_yaml_pendientes_validos(tmp_path: Path) -> None:
    horarios_dir = _build(tmp_path, BASE_VALIDA.format(fila="08:00  08:10  08:20"))
    paradas_con_pendientes = (FIXTURES / "paradas_base.yaml").read_text(
        encoding="utf-8"
    ) + "\npendientes: [P12]\n"
    (horarios_dir / "paradas.yaml").write_text(paradas_con_pendientes, encoding="utf-8")
    resultado = formato.validar(horarios_dir)
    assert resultado.errores == []
    assert resultado.modelo is not None
    assert modelo_de(resultado).pendientes == ("P12",)
    assert any("pendiente P12" in a for a in resultado.avisos)


def test_paradas_yaml_pendiente_malformado_es_error(tmp_path: Path) -> None:
    horarios_dir = _build(tmp_path, BASE_VALIDA.format(fila="08:00  08:10  08:20"))
    paradas_con_pendientes = (FIXTURES / "paradas_base.yaml").read_text(
        encoding="utf-8"
    ) + "\npendientes: [no-valido]\n"
    (horarios_dir / "paradas.yaml").write_text(paradas_con_pendientes, encoding="utf-8")
    resultado = formato.validar(horarios_dir)
    assert any("pendiente inválido 'no-valido'" in e for e in resultado.errores)


def test_observacion_con_marcador_desconocido_es_error(tmp_path: Path) -> None:
    linea = BASE_VALIDA.format(fila="08:00  08:10  08:20")
    horarios_dir = _build(
        tmp_path, linea, observaciones_fixture="observaciones_marcador_desconocido.yaml"
    )
    resultado = formato.validar(horarios_dir)
    assert any("marcador desconocido '{otro}'" in e for e in resultado.errores)


def test_observacion_con_marcador_telefono_no_da_error(tmp_path: Path) -> None:
    linea = BASE_VALIDA.format(fila="08:00  08:10  08:20")
    horarios_dir = _build(tmp_path, linea)  # observaciones_base.yaml usa {telefono}
    resultado = formato.validar(horarios_dir)
    assert resultado.errores == []


def test_tablas_con_misma_temporada_y_dias_se_distinguen_en_los_avisos(tmp_path: Path) -> None:
    # Dos tablas de la misma línea comparten temporada+dias (p.ej. ida y
    # vuelta, ambas anual/sábado): cada una debe llevar una etiqueta distinta
    # ("tabla 1 de 2" / "tabla 2 de 2") para que un aviso o error sepa decir a
    # cuál se refiere.
    linea = """\
nombre: Línea de prueba
temporadas:
  anual: todo el año
dias:
  anual:
    lunes-viernes: sin_servicio
    sabado: horario
    domingos-festivos: sin_servicio
horarios:
  - temporada: anual
    dias: sabado
    tabla: |
      AAA    BBB    CCC
      08:00  08:10  08:20  | P01
  - temporada: anual
    dias: sabado
    tabla: |
      CCC    BBB    AAA
      09:00  09:10  09:20  | P01
"""
    horarios_dir = _build(tmp_path, linea)
    resultado = formato.validar(horarios_dir)
    assert resultado.errores == []
    etiquetas_pendiente = {a for a in resultado.avisos if "fila 1: pendiente P01" in a}
    assert any("tabla 1 de 2" in a for a in etiquetas_pendiente)
    assert any("tabla 2 de 2" in a for a in etiquetas_pendiente)
    # las dos etiquetas deben ser distintas entre sí
    assert len(etiquetas_pendiente) == 2


# ── no_vendibles en paradas.yaml (P12b) ─────────────────────────────────────

_LINEA_A_B = """\
nombre: Línea de prueba
temporadas:
  anual: todo el año
dias:
  anual:
    lunes-viernes: horario
    sabado: sin_servicio
    domingos-festivos: sin_servicio
horarios:
  - temporada: anual
    dias: lunes-viernes
    tabla: |
      AAA    BBB
      08:00  08:10
"""


def _validar_con_no_vendibles(tmp_path: Path, bloque: str) -> formato.Resultado:
    horarios_dir = _build(tmp_path, _LINEA_A_B)
    paradas = horarios_dir / "paradas.yaml"
    paradas.write_text(paradas.read_text(encoding="utf-8") + "\n" + bloque, encoding="utf-8")
    return formato.validar(horarios_dir)


def test_no_vendibles_valido(tmp_path: Path) -> None:
    resultado = _validar_con_no_vendibles(tmp_path, "no_vendibles:\n  - [pueblo-a, pueblo-b]\n")
    assert resultado.errores == []
    assert modelo_de(resultado).no_vendibles == frozenset({frozenset({"pueblo-a", "pueblo-b"})})
    assert not any("no_vendibles" in a for a in resultado.avisos)


def test_no_vendibles_localidad_sin_definir_es_error(tmp_path: Path) -> None:
    resultado = _validar_con_no_vendibles(tmp_path, "no_vendibles:\n  - [pueblo-a, pueblo-zzz]\n")
    assert any(
        "paradas.yaml" in e and "no_vendibles" in e and "pueblo-zzz" in e for e in resultado.errores
    )


def test_no_vendibles_misma_localidad_dos_veces_es_error(tmp_path: Path) -> None:
    resultado = _validar_con_no_vendibles(tmp_path, "no_vendibles:\n  - [pueblo-a, pueblo-a]\n")
    assert any("la misma localidad dos veces" in e for e in resultado.errores)


def test_no_vendibles_par_repetido_es_error(tmp_path: Path) -> None:
    resultado = _validar_con_no_vendibles(
        tmp_path, "no_vendibles:\n  - [pueblo-a, pueblo-b]\n  - [pueblo-a, pueblo-b]\n"
    )
    assert any("repetido" in e for e in resultado.errores)


def test_no_vendibles_par_repetido_invertido_es_error(tmp_path: Path) -> None:
    resultado = _validar_con_no_vendibles(
        tmp_path, "no_vendibles:\n  - [pueblo-a, pueblo-b]\n  - [pueblo-b, pueblo-a]\n"
    )
    assert any("repetido" in e for e in resultado.errores)


def test_no_vendibles_elemento_que_no_es_par_es_error(tmp_path: Path) -> None:
    resultado = _validar_con_no_vendibles(
        tmp_path, "no_vendibles:\n  - [pueblo-a, pueblo-b, pueblo-c]\n"
    )
    assert any("elemento inválido" in e for e in resultado.errores)


def test_no_vendibles_par_que_ninguna_linea_conecta_avisa(tmp_path: Path) -> None:
    # la línea de prueba solo conecta A-B; A-C no lo conecta nadie.
    resultado = _validar_con_no_vendibles(tmp_path, "no_vendibles:\n  - [pueblo-a, pueblo-c]\n")
    assert resultado.errores == []
    assert any(
        "no_vendibles" in a and "pueblo-a" in a and "pueblo-c" in a and "ninguna línea conecta" in a
        for a in resultado.avisos
    )


def test_horarios_real_declara_los_tres_no_vendibles_de_p12b() -> None:
    resultado = formato.validar(HORARIOS_REAL)
    assert modelo_de(resultado).no_vendibles == frozenset(
        {
            frozenset({"cordoba", "campus-de-rabanales"}),
            frozenset({"cordoba", "alcolea"}),
            frozenset({"campus-de-rabanales", "alcolea"}),
        }
    )
    assert not any("no_vendibles" in a for a in resultado.avisos)


# ── celda `llegada>salida` (ciclo C1, P21) ───────────────────────────────────


def _validar_fila(tmp_path: Path, fila: str) -> formato.Resultado:
    return formato.validar(_build(tmp_path, BASE_VALIDA.format(fila=fila)))


def test_celda_llegada_salida_valida_en_parada_intermedia(tmp_path: Path) -> None:
    resultado = _validar_fila(tmp_path, "08:00  08:10>08:45  09:00")
    assert resultado.errores == []
    viaje = modelo_de(resultado).lineas["linea-prueba"].viajes[0]
    assert (viaje.pasos[0].llegada, viaje.pasos[0].salida) == ("08:00", "08:00")
    assert (viaje.pasos[1].llegada, viaje.pasos[1].salida) == ("08:10", "08:45")


def test_celda_llegada_salida_admite_letra_de_parada_al_final(tmp_path: Path) -> None:
    resultado = _validar_fila(tmp_path, "08:00  08:10>08:45P  09:00")
    assert resultado.errores == []
    paso = modelo_de(resultado).lineas["linea-prueba"].viajes[0].pasos[1]
    assert paso.observaciones == ("entra_en_pueblo",)


def test_llegada_salida_en_la_primera_celda_es_error(tmp_path: Path) -> None:
    resultado = _validar_fila(tmp_path, "08:00>08:05  08:10  09:00")
    assert any(
        "fila 1: llegada y salida solo en una parada intermedia del viaje ('AAA')" in e
        for e in resultado.errores
    )


def test_llegada_salida_en_la_ultima_celda_con_hora_es_error(tmp_path: Path) -> None:
    resultado = _validar_fila(tmp_path, "08:00  08:10  09:00>09:10")
    assert any(
        "llegada y salida solo en una parada intermedia del viaje ('CCC')" in e
        for e in resultado.errores
    )


def test_llegada_salida_en_la_ultima_celda_con_hora_aunque_siga_un_guion(tmp_path: Path) -> None:
    resultado = _validar_fila(tmp_path, "08:00  08:10>08:20  -")
    assert any("('BBB')" in e and "solo en una parada intermedia" in e for e in resultado.errores)


def test_misma_hora_dos_veces_es_error(tmp_path: Path) -> None:
    resultado = _validar_fila(tmp_path, "08:00  08:10>08:10  09:00")
    assert any(
        "fila 1: misma hora dos veces en 'BBB'; escribe una sola" in e for e in resultado.errores
    )


def test_salida_anterior_a_la_llegada_es_error(tmp_path: Path) -> None:
    resultado = _validar_fila(tmp_path, "08:00  12:30>11:55  13:00")
    assert any(
        "fila 1: la llegada debe ser anterior a la salida en 'BBB' (12:30>11:55)" in e
        for e in resultado.errores
    )


def test_llegada_siguiente_anterior_a_la_salida_previa_es_retroceso(tmp_path: Path) -> None:
    resultado = _validar_fila(tmp_path, "08:00  08:10>08:45  08:30")
    assert any("las horas retroceden en 'CCC' (08:30)" in e for e in resultado.errores)


def test_llegada_igual_a_la_salida_previa_no_es_retroceso(tmp_path: Path) -> None:
    resultado = _validar_fila(tmp_path, "08:00  08:10>08:45  08:45")
    assert resultado.errores == []


# ── mismo autobús: `bus:<id>` y aviso heurístico (ciclo C1, T-1) ─────────────

CICLO_C = FIXTURES / "horarios_cicloC"

LINEA_TPL = """\
nombre: {nombre}
avisos: []
no_circula: []
temporadas:
  anual: todo el año
dias:
  anual: {{ lunes: sin_datos, martes: sin_datos, miercoles: sin_datos,
    jueves: sin_datos, viernes: sin_datos, sabado: sin_datos,
    domingo: sin_datos, festivos: sin_datos }}
horarios:
{tablas}
pendientes: []
"""


def _tabla(dias: str, cabecera: str, *filas: str) -> str:
    cuerpo = "\n".join(f"      {f}" for f in (cabecera, *filas))
    return f"  - temporada: anual\n    dias: {dias}\n    tabla: |\n{cuerpo}\n"


def _linea(nombre: str, *tablas: str) -> str:
    return LINEA_TPL.format(nombre=nombre, tablas="".join(tablas))


def _lv(nombre: str, cabecera: str, fila: str) -> str:
    return _linea(nombre, _tabla("lunes-viernes", cabecera, fila))


def _ciclo_c(
    tmp_path: Path, extra: dict[str, str] | None = None, quitar: tuple[str, ...] = ()
) -> Path:
    destino = tmp_path / "horarios"
    shutil.copytree(CICLO_C, destino)
    for nombre in quitar:
        (destino / "lineas" / f"{nombre}.yaml").unlink()
    for nombre, texto in (extra or {}).items():
        (destino / "lineas" / f"{nombre}.yaml").write_text(texto, encoding="utf-8")
    return destino


def _errores_bus(tmp_path: Path, **lineas: str) -> formato.Resultado:
    """Valida la fixture sin vecina/larga/corta/paso más las líneas dadas."""
    destino = _ciclo_c(
        tmp_path,
        extra=lineas,
        quitar=("larga", "corta", "paso", "vecina"),
    )
    return formato.validar(destino)


def test_fixture_ciclo_c_valida_sin_errores() -> None:
    resultado = formato.validar(CICLO_C)
    assert resultado.errores == []
    assert resultado.modelo is not None


def test_fixture_ciclo_c_lee_llegada_salida_y_bus() -> None:
    modelo = modelo_de(formato.validar(CICLO_C))
    viaje = modelo.lineas["larga"].viajes[0]
    pnr = next(p for p in viaje.pasos if p.parada == "PNR")
    assert (pnr.llegada, pnr.salida) == ("11:55", "12:30")
    assert viaje.bus == "cor-1030"
    assert modelo.lineas["corta"].viajes[1].bus is None


def test_bus_compartido_por_dos_tablas_de_una_linea_y_un_viaje_de_otra_es_valido() -> None:
    # paso.yaml (lunes-jueves y viernes) + un viaje lunes-viernes de corta.yaml
    resultado = formato.validar(CICLO_C)
    assert resultado.errores == []
    ids = [
        v.bus
        for lid in ("paso", "corta")
        for v in modelo_de(resultado).lineas[lid].viajes
        if v.bus == "pas-1500"
    ]
    assert len(ids) == 3


def test_aviso_heuristico_texto_y_un_solo_aviso_por_par(tmp_path: Path) -> None:
    resultado = formato.validar(CICLO_C)
    avisos = [a for a in resultado.avisos if "posible mismo autobús" in a]
    # vecina discrepa con larga y con corta; vecina tiene dos tablas
    # (lunes-viernes y lunes-jueves) pero cada par sale una sola vez.
    assert len(avisos) == 2
    for aviso in avisos:
        assert "posible mismo autobús con horas distintas: " in aviso and aviso.endswith(
            "(no se fusionará)"
        )
        assert "Córdoba 10:30 en ambas y Espiel 11:15 frente a 11:20" in aviso
    par_larga = "'Los Blázquez – Córdoba' y 'Vecina – Córdoba'"
    par_corta = "'Peñarroya – Córdoba' y 'Vecina – Córdoba'"
    assert sum(par_larga in a for a in avisos) == 1
    assert sum(par_corta in a for a in avisos) == 1


def test_no_hay_aviso_si_el_par_esta_declarado_con_el_mismo_bus(tmp_path: Path) -> None:
    resultado = formato.validar(CICLO_C)
    assert not any(
        "'Los Blázquez – Córdoba' y 'Peñarroya – Córdoba'" in a
        or "'Peñarroya – Córdoba' y 'Los Blázquez – Córdoba'" in a
        for a in resultado.avisos
    )


def test_bus_en_un_solo_viaje_es_error(tmp_path: Path) -> None:
    resultado = _errores_bus(
        tmp_path,
        a=_lv("A", "COR VAC ESP", "10:00 10:30 11:00 | bus:solo-1"),
    )
    assert any(
        "bus:solo-1 aparece en un solo viaje" in e and "a.yaml" in e and "fila 1" in e
        for e in resultado.errores
    )


def test_bus_sin_ningun_dia_en_comun_es_error(tmp_path: Path) -> None:
    resultado = _errores_bus(
        tmp_path,
        a=_linea(
            "A",
            _tabla("lunes-jueves", "COR VAC ESP", "10:00 10:30 11:00 | bus:x"),
            _tabla("lunes-jueves", "COR VAC BEL", "12:00 12:30 13:00"),
        ),
        b=_linea("B", _tabla("sabado", "COR VAC ESP", "10:00 10:30 11:00 | bus:x")),
    )
    assert any("bus:x: los viajes no coinciden en ningún día" in e for e in resultado.errores)


def test_bus_con_menos_de_2_localidades_comunes_es_error(tmp_path: Path) -> None:
    resultado = _errores_bus(
        tmp_path,
        a=_lv("A", "COR VAC", "10:00 10:30 | bus:x"),
        b=_lv("B", "COR ESP", "10:00 10:40 | bus:x"),
    )
    assert any("bus:x: comparten menos de 2 localidades" in e for e in resultado.errores)


def test_bus_con_horas_distintas_en_parada_comun_es_error(tmp_path: Path) -> None:
    resultado = _errores_bus(
        tmp_path,
        a=_lv("A", "COR VAC ESP", "10:00 10:30 11:00 | bus:x"),
        b=_lv("B", "COR VAC ESP", "10:00 10:35 11:00 | bus:x"),
    )
    errores = [e for e in resultado.errores if "bus:x: horas distintas en 'VAC'" in e]
    assert len(errores) == 1
    assert "a.yaml" in errores[0] and "b.yaml" in errores[0]
    assert "10:30" in errores[0] and "10:35" in errores[0]


def test_bus_salida_distinta_en_parada_intermedia_es_error(tmp_path: Path) -> None:
    # VAC no es la última de ninguno de los dos viajes: la salida cuenta.
    resultado = _errores_bus(
        tmp_path,
        a=_lv("A", "COR VAC ESP", "10:00 10:30>10:40 11:00 | bus:x"),
        b=_lv("B", "COR VAC ESP", "10:00 10:30 11:00 | bus:x"),
    )
    assert any("horas distintas en 'VAC'" in e and "10:30>10:40" in e for e in resultado.errores)


def test_bus_salida_de_la_ultima_parada_de_un_viaje_no_se_compara(tmp_path: Path) -> None:
    resultado = _errores_bus(
        tmp_path,
        a=_lv("A", "COR VAC ESP", "10:00 10:30 11:00 | bus:x"),
        b=_lv("B", "COR VAC ESP BEL", "10:00 10:30 11:00>11:10 11:30 | bus:x"),
    )
    assert resultado.errores == []


def test_bus_con_paradas_distintas_en_una_localidad_es_error(tmp_path: Path) -> None:
    resultado = _errores_bus(
        tmp_path,
        a=_lv("A", "COR VRE BEL", "10:00 10:30 11:00 | bus:x"),
        b=_lv("B", "COR VRC BEL", "10:00 10:30 11:00 | bus:x"),
    )
    assert any(
        "bus:x: paradas distintas en Villanueva del Rey (VRE / VRC" in e for e in resultado.errores
    )


def test_bus_dos_viajes_de_la_misma_linea_con_dias_solapados_es_error(tmp_path: Path) -> None:
    resultado = _errores_bus(
        tmp_path,
        a=_linea(
            "A",
            _tabla("lunes-viernes", "COR VAC ESP", "10:00 10:30 11:00 | bus:x"),
            _tabla("lunes-jueves", "COR VAC ESP", "10:00 10:30 11:00 | bus:x"),
        ),
    )
    assert any(
        "bus:x: dos viajes de la misma línea 'a' con días solapados" in e for e in resultado.errores
    )


def test_bus_de_la_misma_linea_sin_dias_comunes_es_error(tmp_path: Path) -> None:
    resultado = _errores_bus(
        tmp_path,
        a=_linea(
            "A",
            _tabla("lunes-jueves", "COR VAC ESP", "10:00 10:30 11:00 | bus:x"),
            _tabla("sabado", "COR VAC ESP", "10:00 10:30 11:00 | bus:x"),
        ),
    )
    assert any("los viajes no coinciden en ningún día" in e for e in resultado.errores)


def test_bus_con_identificador_mal_formado_es_error(tmp_path: Path) -> None:
    for numero, malo in enumerate(("Cor1", "cor_1", "cor.1", "")):
        sub = tmp_path / f"caso{numero}"
        sub.mkdir()
        resultado = _errores_bus(
            sub,
            a=_lv("A", "COR VAC", f"10:00 10:30 | bus:{malo}"),
        )
        assert any(
            f"identificador de autobús inválido 'bus:{malo}'" in e for e in resultado.errores
        ), malo


def test_dos_bus_en_el_mismo_viaje_es_error(tmp_path: Path) -> None:
    resultado = _errores_bus(
        tmp_path,
        a=_lv("A", "COR VAC", "10:00 10:30 | bus:x bus:y"),
    )
    assert any("más de un 'bus:' en el mismo viaje" in e for e in resultado.errores)


def test_bus_y_pendiente_conviven_en_la_misma_fila(tmp_path: Path) -> None:
    resultado = _errores_bus(
        tmp_path,
        a=_lv("A", "COR VAC ESP", "10:00 10:30 11:00 | bus:x P01"),
        b=_lv("B", "COR VAC ESP", "10:00 10:30 11:00 | bus:x"),
    )
    assert resultado.errores == []
    viaje = modelo_de(resultado).lineas["a"].viajes[0]
    assert viaje.bus == "x" and viaje.pendientes == ("P01",)


def test_horarios_real_tiene_exactamente_7_avisos_de_posible_mismo_autobus() -> None:
    resultado = formato.validar(HORARIOS_REAL)
    assert resultado.errores == []
    posibles = [a for a in resultado.avisos if "posible mismo autobús" in a]
    assert len(posibles) == 7
    pares = [
        ("Belalcázar – Córdoba", "Villaviciosa – Córdoba"),
        ("Belalcázar – Córdoba", "Belalcázar – Pozoblanco"),
        ("Belalcázar – Córdoba", "Pozoblanco – Córdoba"),
        ("Los Blázquez", "Pozoblanco – Córdoba"),
        # Nuevo con el Excel del 07/10/2026: El Vacar 10:55 en ambas, pero
        # Córdoba 11:30 (BLAZQUEZ) frente a 11:25 (VILLAVIC).
        ("Los Blázquez", "Villaviciosa – Córdoba"),
        ("Peñarroya – Córdoba", "Pozoblanco – Córdoba"),
        ("Peñarroya – Córdoba", "Villaviciosa – Córdoba"),
    ]
    for a, b in pares:
        assert sum(f"'{a}' y '{b}'" in p for p in posibles) == 1, (a, b)


# ── Localidades pendientes (ciclo C2, P15/P32) ────────────────────────────


def _pendientes(
    tmp_path: Path,
    paradas: Sequence[tuple[str, str]] = (),
    observaciones: Sequence[tuple[str, str]] = (),
) -> tuple[formato.Resultado, Path]:
    """Copia horarios_pendientes/ a tmp_path aplicando sustituciones de texto
    (old, new) sobre paradas.yaml y observaciones.yaml; devuelve (resultado,
    ruta de paradas.yaml)."""
    destino = tmp_path / "horarios"
    shutil.copytree(FIXTURES / "horarios_pendientes", destino)
    for nombre, cambios in (
        ("paradas.yaml", paradas),
        ("observaciones.yaml", observaciones),
    ):
        ruta = destino / nombre
        texto = ruta.read_text(encoding="utf-8")
        for old, new in cambios:
            assert old in texto, old
            texto = texto.replace(old, new)
        ruta.write_text(texto, encoding="utf-8")
    return formato.validar(destino), destino / "paradas.yaml"


def test_pendientes_fixture_valida_sin_errores(tmp_path: Path) -> None:
    resultado, ruta = _pendientes(tmp_path)
    assert resultado.errores == []
    aldea = modelo_de(resultado).localidades["aldea-a"]
    assert (aldea.pendiente, aldea.ver, aldea.minutos, aldea.aviso) == (
        "P32",
        "pueblo-a",
        4,
        "pasa_por_aldea_a",
    )
    assert f"{ruta}: localidad pendiente 'aldea-a' (P32)" in resultado.avisos
    assert f"{ruta}: localidad pendiente 'aldea-b' (P32)" in resultado.avisos
    # una localidad pendiente sin paradas no cuenta como "sin uso"
    assert not any("Localidades definidas que ninguna" in a for a in resultado.avisos)


def test_pendiente_sin_ver_es_error(tmp_path: Path) -> None:
    r, ruta = _pendientes(tmp_path, [("    ver: pueblo-a\n", "")])
    assert (
        f"{ruta}: localidad 'aldea-a': 'pendiente' sin 'ver' (localidad en cuyo lugar se consulta)"
    ) in r.errores


def test_ver_sin_pendiente_es_error(tmp_path: Path) -> None:
    r, ruta = _pendientes(
        tmp_path,
        [
            (
                "pueblo-a: { nombre: Pueblo A }",
                "pueblo-a: { nombre: Pueblo A, ver: pueblo-b }",
            )
        ],
    )
    assert f"{ruta}: localidad 'pueblo-a': 'ver' sin 'pendiente'" in r.errores


def test_pendiente_malformado_es_error(tmp_path: Path) -> None:
    r, ruta = _pendientes(tmp_path, [("pendiente: P32", "pendiente: X1")])
    assert (
        f"{ruta}: localidad 'aldea-a': pendiente inválido 'X1' (debe cumplir P\\d{{2}})"
    ) in r.errores


def test_pendiente_sin_minutos_es_error(tmp_path: Path) -> None:
    r, ruta = _pendientes(tmp_path, [("    minutos: 4\n", "")])
    assert (
        f"{ruta}: localidad 'aldea-a': 'pendiente' sin 'minutos' (distancia a la localidad 'ver')"
    ) in r.errores


@pytest.mark.parametrize("valor", ["0", "61", "abc", "4.5", "true"])
def test_minutos_fuera_de_rango_o_no_entero_es_error(tmp_path: Path, valor: str) -> None:
    r, ruta = _pendientes(tmp_path, [("minutos: 4", f"minutos: {valor}")])
    assert any(
        e.startswith(f"{ruta}: localidad 'aldea-a': 'minutos' debe ser un entero entre 1 y 60")
        for e in r.errores
    ), r.errores


def test_minutos_sin_pendiente_es_error(tmp_path: Path) -> None:
    r, ruta = _pendientes(
        tmp_path,
        [
            (
                "pueblo-c: { nombre: Pueblo C }",
                "pueblo-c: { nombre: Pueblo C, minutos: 3 }",
            )
        ],
    )
    assert f"{ruta}: localidad 'pueblo-c': 'minutos' sin 'pendiente'" in r.errores


def test_aviso_sin_pendiente_es_error(tmp_path: Path) -> None:
    r, ruta = _pendientes(
        tmp_path,
        [
            (
                "pueblo-c: { nombre: Pueblo C }",
                "pueblo-c: { nombre: Pueblo C, aviso: para_en_aldea_b }",
            )
        ],
    )
    assert f"{ruta}: localidad 'pueblo-c': 'aviso' sin 'pendiente'" in r.errores


def test_pendiente_fuera_de_la_lista_de_paradas_es_error(tmp_path: Path) -> None:
    r, ruta = _pendientes(tmp_path, [("pendientes: [P32]", "pendientes: [P19]")])
    assert (
        f"{ruta}: localidad pendiente 'aldea-a': P32 no está en 'pendientes' de paradas.yaml"
    ) in r.errores


def test_ver_sin_definir_es_error(tmp_path: Path) -> None:
    r, ruta = _pendientes(tmp_path, [("ver: pueblo-a", "ver: nada")])
    assert (
        f"{ruta}: localidad pendiente 'aldea-a': 'ver' referencia una localidad "
        "sin definir ('nada')"
    ) in r.errores


def test_ver_a_si_misma_es_error(tmp_path: Path) -> None:
    r, ruta = _pendientes(tmp_path, [("ver: pueblo-a", "ver: aldea-a")])
    assert (f"{ruta}: localidad pendiente 'aldea-a': 'ver' apunta a sí misma") in r.errores


def test_ver_a_otra_pendiente_es_error(tmp_path: Path) -> None:
    r, ruta = _pendientes(tmp_path, [("ver: pueblo-a", "ver: aldea-b")])
    assert (
        f"{ruta}: localidad pendiente 'aldea-a': 'ver' apunta a otra localidad "
        "pendiente ('aldea-b')"
    ) in r.errores


def test_pendiente_con_paradas_es_error(tmp_path: Path) -> None:
    r, ruta = _pendientes(
        tmp_path,
        [("paradas:\n", "paradas:\n  ALD: { nombre: Aldea A, localidad: aldea-a }\n")],
    )
    assert (
        f"{ruta}: localidad pendiente 'aldea-a': una localidad pendiente no "
        "puede tener paradas (['ALD'])"
    ) in r.errores


def test_aviso_de_localidad_sin_definir_es_error(tmp_path: Path) -> None:
    r, ruta = _pendientes(tmp_path, [("aviso: pasa_por_aldea_a", "aviso: no_existe")])
    assert (
        f"{ruta}: localidad pendiente 'aldea-a': 'aviso' referencia una "
        "observación sin definir ('no_existe')"
    ) in r.errores


def test_aviso_que_no_es_tipo_aviso_es_error(tmp_path: Path) -> None:
    r, ruta = _pendientes(
        tmp_path,
        paradas=[("aviso: pasa_por_aldea_a", "aviso: a_demanda")],
        observaciones=[
            (
                "pasa_por_aldea_a:",
                "a_demanda:\n  letra: D\n  tipo: condicion\n  ambitos: [viaje]\n"
                '  texto: "Solo a demanda."\n\npasa_por_aldea_a:',
            )
        ],
    )
    assert (
        f"{ruta}: localidad pendiente 'aldea-a': 'aviso' 'a_demanda' no es una "
        "observación de tipo aviso"
    ) in r.errores


def test_aviso_sin_ambito_viaje_es_error(tmp_path: Path) -> None:
    r, ruta = _pendientes(
        tmp_path,
        observaciones=[
            (
                "pasa_por_aldea_a:\n  tipo: aviso\n  ambitos: [viaje]",
                "pasa_por_aldea_a:\n  tipo: aviso\n  ambitos: [linea]",
            ),
        ],
    )
    assert any(
        e.startswith(
            f"{ruta}: localidad pendiente 'aldea-a': 'aviso' "
            "'pasa_por_aldea_a' no tiene ámbito 'viaje'"
        )
        for e in r.errores
    ), r.errores


def test_aviso_cuyo_texto_no_contiene_los_minutos_avisa(tmp_path: Path) -> None:
    r, ruta = _pendientes(tmp_path, [("minutos: 4", "minutos: 5")])
    assert r.errores == []
    assert (
        f"{ruta}: localidad pendiente 'aldea-a': el texto de la observación "
        "'pasa_por_aldea_a' no contiene los minutos declarados (5)"
    ) in r.avisos


def test_horarios_real_no_tiene_localidades_pendientes() -> None:
    resultado = formato.validar(HORARIOS_REAL)
    assert resultado.errores == []
    pendientes = {
        lid: loc.pendiente
        for lid, loc in modelo_de(resultado).localidades.items()
        if loc.pendiente is not None
    }
    # P32 cerrada el 07/10/2026: Rivero y Los Mochos son localidades normales.
    assert pendientes == {}
    assert len(resultado.avisos) == 11


# ── P18: pueblos por línea (ciclo C3) ────────────────────────────────────


def _con_paradas(tmp_path: Path, texto_paradas: str) -> Path:
    horarios_dir = _build(tmp_path, BASE_VALIDA.format(fila="08:00  08:10  08:20"))
    (horarios_dir / "paradas.yaml").write_text(texto_paradas, encoding="utf-8")
    return horarios_dir


_PARADAS_MIN = """\
localidades:
  pueblo-a: { nombre: Pueblo A%s }
  pueblo-b: { nombre: Pueblo B }
  pueblo-c: { nombre: Pueblo C }
paradas:
  AAA: { nombre: Pueblo A, localidad: pueblo-a }
  BBB: { nombre: Pueblo B, localidad: pueblo-b }
  CCC: { nombre: Pueblo C, localidad: pueblo-c }
"""


def test_zonas_en_paradas_es_campo_obsoleto(tmp_path: Path) -> None:
    horarios_dir = _con_paradas(tmp_path, "zonas:\n  z: Zona\n" + _PARADAS_MIN % "")
    resultado = formato.validar(horarios_dir)
    ruta = horarios_dir / "paradas.yaml"
    assert (
        f"{ruta}: campo obsoleto 'zonas' (P18: los pueblos se agrupan por línea)"
        in resultado.errores
    )


def test_zona_en_localidad_es_campo_obsoleto(tmp_path: Path) -> None:
    horarios_dir = _con_paradas(tmp_path, _PARADAS_MIN % ", zona: z")
    resultado = formato.validar(horarios_dir)
    ruta = horarios_dir / "paradas.yaml"
    assert (
        f"{ruta}: localidad 'pueblo-a': campo obsoleto 'zona' (P18: los pueblos "
        "se agrupan por línea)"
    ) in resultado.errores


def test_localidad_solo_necesita_nombre(tmp_path: Path) -> None:
    horarios_dir = _con_paradas(tmp_path, _PARADAS_MIN % "")
    assert formato.validar(horarios_dir).errores == []


def test_nombre_largo_sin_nombre_corto_es_error(tmp_path: Path) -> None:
    linea = BASE_VALIDA.format(fila="08:00  08:10  08:20").replace(
        "nombre: Línea de prueba", "nombre: " + "N" * 25, 1
    )
    horarios_dir = _build(tmp_path, linea)
    resultado = formato.validar(horarios_dir)
    ruta = horarios_dir / "lineas" / "linea-prueba.yaml"
    assert (
        f"{ruta}: el nombre de la línea ('{'N' * 25}') tiene 25 caracteres "
        "(máximo 24 para el título de fila de WhatsApp): añade 'nombre_corto'"
    ) in resultado.errores


def test_nombre_largo_con_nombre_corto_valido(tmp_path: Path) -> None:
    linea = BASE_VALIDA.format(fila="08:00  08:10  08:20").replace(
        "nombre: Línea de prueba",
        "nombre: " + "N" * 25 + "\nnombre_corto: Corto",
        1,
    )
    horarios_dir = _build(tmp_path, linea)
    resultado = formato.validar(horarios_dir)
    assert resultado.errores == []
    linea_m = modelo_de(resultado).lineas["linea-prueba"]
    assert linea_m.nombre_corto == "Corto"
    assert linea_m.titulo == "Corto"


def test_titulo_sin_nombre_corto_es_el_nombre(tmp_path: Path) -> None:
    horarios_dir = _build(tmp_path, BASE_VALIDA.format(fila="08:00  08:10  08:20"))
    linea = modelo_de(formato.validar(horarios_dir)).lineas["linea-prueba"]
    assert linea.titulo == "Línea de prueba"


def test_nombre_corto_demasiado_largo_es_error(tmp_path: Path) -> None:
    linea = BASE_VALIDA.format(fila="08:00  08:10  08:20").replace(
        "nombre: Línea de prueba",
        "nombre: Línea de prueba\nnombre_corto: " + "C" * 25,
        1,
    )
    horarios_dir = _build(tmp_path, linea)
    resultado = formato.validar(horarios_dir)
    ruta = horarios_dir / "lineas" / "linea-prueba.yaml"
    assert (
        f"{ruta}: 'nombre_corto' ('{'C' * 25}') tiene 25 caracteres; el máximo "
        "es 24 (título de fila de WhatsApp)"
    ) in resultado.errores


def test_nombre_corto_vacio_es_error(tmp_path: Path) -> None:
    linea = BASE_VALIDA.format(fila="08:00  08:10  08:20").replace(
        "nombre: Línea de prueba",
        "nombre: Línea de prueba\nnombre_corto: ''",
        1,
    )
    horarios_dir = _build(tmp_path, linea)
    resultado = formato.validar(horarios_dir)
    ruta = horarios_dir / "lineas" / "linea-prueba.yaml"
    assert f"{ruta}: 'nombre_corto' debe ser un texto no vacío ('')" in resultado.errores


def test_nombre_corto_no_es_texto_es_error(tmp_path: Path) -> None:
    linea = BASE_VALIDA.format(fila="08:00  08:10  08:20").replace(
        "nombre: Línea de prueba",
        "nombre: Línea de prueba\nnombre_corto: [a, b]",
        1,
    )
    horarios_dir = _build(tmp_path, linea)
    resultado = formato.validar(horarios_dir)
    ruta = horarios_dir / "lineas" / "linea-prueba.yaml"
    assert f"{ruta}: 'nombre_corto' debe ser un texto no vacío (['a', 'b'])" in resultado.errores


def test_dos_lineas_con_el_mismo_titulo_es_error(tmp_path: Path) -> None:
    linea = BASE_VALIDA.format(fila="08:00  08:10  08:20")
    horarios_dir = _build(tmp_path, linea)
    (horarios_dir / "lineas" / "otra-linea.yaml").write_text(
        linea.replace("nombre: Línea de prueba", "nombre: LINEA DE PRUEBA", 1),
        encoding="utf-8",
    )
    resultado = formato.validar(horarios_dir)
    lineas_dir = horarios_dir / "lineas"
    assert (
        f"{lineas_dir}: las líneas ['linea-prueba', 'otra-linea'] tienen el mismo "
        "título en el bot ('linea prueba'): "
        f"{lineas_dir / 'linea-prueba.yaml'}, {lineas_dir / 'otra-linea.yaml'}"
    ) in resultado.errores


def test_id_de_linea_invalido_es_error(tmp_path: Path) -> None:
    horarios_dir = _build(
        tmp_path,
        BASE_VALIDA.format(fila="08:00  08:10  08:20"),
        linea_nombre="Linea_Rara",
    )
    resultado = formato.validar(horarios_dir)
    ruta = horarios_dir / "lineas" / "Linea_Rara.yaml"
    assert any(
        e.startswith(f"{ruta}: id de línea inválido 'Linea_Rara'") for e in resultado.errores
    )


def test_horarios_real_tiene_11_avisos_y_4_nombres_cortos() -> None:
    resultado = formato.validar(HORARIOS_REAL)
    assert resultado.errores == []
    assert len(resultado.avisos) == 11
    cortos = {
        lid: linea.nombre_corto
        for lid, linea in modelo_de(resultado).lineas.items()
        if linea.nombre_corto
    }
    assert cortos == {
        "adamuz-cordoba": "Adamuz – Córdoba",
        "fuente-carreteros-cordoba": "F. Carreteros – Córdoba",
        "pozoblanco-estacion-ave": "Estación AVE Villanueva",
        "santa-eufemia-villaralto-pozoblanco": "Santa Eufemia-Villaralto",
    }
    assert all(len(linea.titulo) <= 24 for linea in modelo_de(resultado).lineas.values())


PARADAS_OK = """\
localidades:
  pueblo-a: { nombre: Pueblo A }
  pueblo-b: { nombre: Pueblo B }
  pueblo-c: { nombre: Pueblo C }
paradas:
  AAA: { nombre: Pueblo A, localidad: pueblo-a }
  BBB: { nombre: Pueblo B, localidad: pueblo-b }
  CCC: { nombre: Pueblo C, localidad: pueblo-c }
"""


def _errores_con_paradas(
    tmp_path: Path, paradas: str, observaciones: str | None = None
) -> list[str]:
    horarios_dir = _build(tmp_path, BASE_VALIDA.format(fila="08:00  08:10  08:20"))
    (horarios_dir / "paradas.yaml").write_text(paradas, encoding="utf-8")
    if observaciones is not None:
        (horarios_dir / "observaciones.yaml").write_text(observaciones, encoding="utf-8")
    return formato.validar(horarios_dir).errores


def test_parada_con_coma_sin_comillas_es_error_con_pista(tmp_path: Path) -> None:
    paradas = PARADAS_OK.replace(
        "{ nombre: Pueblo B, localidad: pueblo-b }",
        "{ nombre: B (b, c), localidad: pueblo-b }",
    )
    errores = _errores_con_paradas(tmp_path, paradas)
    assert any(
        "parada 'BBB'" in e
        and "campo desconocido 'c)'" in e
        and "nombre con coma sin comillas" in e
        for e in errores
    ), errores


def test_localidad_con_clave_desconocida_es_error(tmp_path: Path) -> None:
    paradas = PARADAS_OK.replace(
        "pueblo-a: { nombre: Pueblo A }", "pueblo-a: { nombre: Pueblo A, rara: 1 }"
    )
    errores = _errores_con_paradas(tmp_path, paradas)
    assert any("localidad 'pueblo-a'" in e and "campo desconocido 'rara'" in e for e in errores), (
        errores
    )


def test_paradas_yaml_clave_desconocida_en_nivel_superior_es_error(tmp_path: Path) -> None:
    errores = _errores_con_paradas(tmp_path, PARADAS_OK + "rarezas: {}\n")
    assert any("campo desconocido 'rarezas'" in e for e in errores), errores


def test_observacion_con_clave_desconocida_es_error(tmp_path: Path) -> None:
    obs = (FIXTURES / "observaciones_base.yaml").read_text(encoding="utf-8")
    obs += "\nextra:\n  tipo: aviso\n  ambitos: [viaje]\n  texto: x\n  rara: 1\n"
    errores = _errores_con_paradas(tmp_path, PARADAS_OK, obs)
    assert any("observación 'extra'" in e and "campo desconocido 'rara'" in e for e in errores), (
        errores
    )


def test_zonas_y_zona_obsoletas_dan_solo_su_mensaje(tmp_path: Path) -> None:
    paradas = PARADAS_OK.replace(
        "pueblo-a: { nombre: Pueblo A }", "pueblo-a: { nombre: Pueblo A, zona: z }"
    )
    paradas += "zonas: {}\n"
    errores = _errores_con_paradas(tmp_path, paradas)
    assert any("campo obsoleto 'zonas'" in e for e in errores)
    assert any("campo obsoleto 'zona'" in e for e in errores)
    assert not any("campo desconocido" in e for e in errores), errores
