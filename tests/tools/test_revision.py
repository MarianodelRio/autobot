"""tests/tools/test_revision.py — el HTML de `make revision` contiene cada línea,
temporada, leyenda y pendiente.

Usa un repositorio git real y desechable en tmp_path (git es una herramienta
de desarrollo local, no una API externa, así que no se simula), siguiendo el
patrón de fixtures de tests/test_formato.py."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from packs.bus.formato import validar as validar_horarios
from packs.bus.tests.helpers import modelo_de
from tools import bus_revision as revision

FIXTURES = Path(__file__).parents[2] / "src" / "packs" / "bus" / "tests" / "fixtures"
SLUG = "demo"
DATASET = Path("tenants") / SLUG / "datasets" / "timetable"
TAG = "datos/demo/2026-01-01"


def _git(repo_root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "git",
            "-c",
            "user.email=test@example.com",
            "-c",
            "user.name=Test",
            *args,
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )


LINEA_YAML = """\
nombre: Línea de prueba
avisos: []
no_circula: []
temporadas:
  anual: todo el año
dias:
  anual:
    lunes-viernes: horario
    sabado: sin_servicio
    domingos-festivos: sin_datos
horarios:
  - temporada: anual
    dias: lunes-viernes
    tabla: |
      AAA    BBB    CCC
      08:00  08:10  08:20P | pasa_por_rivero P07
pendientes: [P07]
"""

LINEA_YAML_MODIFICADA = LINEA_YAML.replace("08:10", "08:15")


def _build_repo(tmp_path: Path) -> Path:
    repo_root = tmp_path / "repo"
    horarios_dir = repo_root / DATASET
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
    (horarios_dir / "lineas" / "linea-prueba.yaml").write_text(LINEA_YAML, encoding="utf-8")

    assert _git(repo_root, "init", "-q", "-b", "main").returncode == 0
    assert _git(repo_root, "add", "tenants").returncode == 0
    assert _git(repo_root, "commit", "-q", "-m", "primera version").returncode == 0
    assert _git(repo_root, "tag", TAG).returncode == 0

    (horarios_dir / "lineas" / "linea-prueba.yaml").write_text(
        LINEA_YAML_MODIFICADA, encoding="utf-8"
    )
    assert _git(repo_root, "add", "tenants").returncode == 0
    assert _git(repo_root, "commit", "-q", "-m", "cambio de hora").returncode == 0

    return repo_root


def test_ultimo_tag_encuentra_el_tag(tmp_path: Path) -> None:
    repo_root = _build_repo(tmp_path)
    assert revision._ultimo_tag(repo_root, SLUG) == TAG


def test_ultimo_tag_sin_tags(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo_sin_tags"
    horarios_dir = repo_root / DATASET
    (horarios_dir / "lineas").mkdir(parents=True)
    (horarios_dir / "paradas.yaml").write_text(
        (FIXTURES / "paradas_base.yaml").read_text(encoding="utf-8"), encoding="utf-8"
    )
    (horarios_dir / "observaciones.yaml").write_text(
        (FIXTURES / "observaciones_base.yaml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    _git(repo_root, "init", "-q", "-b", "main")
    _git(repo_root, "add", "tenants")
    _git(repo_root, "commit", "-q", "-m", "sin tags")
    assert revision._ultimo_tag(repo_root, SLUG) is None


def test_resolver_anterior_primera_version(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo_sin_tags"
    (repo_root / DATASET).mkdir(parents=True)
    _git(repo_root, "init", "-q", "-b", "main")
    (repo_root / DATASET / ".gitkeep").write_text("", encoding="utf-8")
    _git(repo_root, "add", "tenants")
    _git(repo_root, "commit", "-q", "-m", "vacio")
    ref, modelo = revision.resolver_anterior(None, repo_root, SLUG)
    assert ref is None
    assert modelo is None


def test_resolver_anterior_con_tag(tmp_path: Path) -> None:
    repo_root = _build_repo(tmp_path)
    ref, modelo = revision.resolver_anterior(None, repo_root, SLUG)
    assert ref == TAG
    assert modelo is not None
    assert "linea-prueba" in modelo.lineas


def test_resolver_anterior_rechaza_una_ref_que_parece_una_opcion(tmp_path: Path) -> None:
    repo_root = _build_repo(tmp_path)
    with pytest.raises(RuntimeError, match="referencia inválida"):
        revision.resolver_anterior("--output=/tmp/x", repo_root, SLUG)


def test_cargar_snapshot_ref_inexistente(tmp_path: Path) -> None:
    repo_root = _build_repo(tmp_path)
    with pytest.raises(RuntimeError, match="no-existe"):
        revision._cargar_snapshot("no-existe", repo_root, tmp_path / "snap", SLUG)


def _generar_para_repo(repo_root: Path, solo_html: bool = True) -> int:
    argv = [SLUG, "--solo-html"] if solo_html else [SLUG]
    return revision.main(argv, repo_root=repo_root)


def test_main_genera_html_con_cambios(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo_root = _build_repo(tmp_path)
    codigo = _generar_para_repo(repo_root)
    assert codigo == 0

    html_path = repo_root / "revision" / SLUG / "horarios.html"
    assert html_path.exists()
    assert not (repo_root / "revision" / SLUG / "horarios.pdf").exists()

    contenido = html_path.read_text(encoding="utf-8")
    assert "Línea de prueba" in contenido
    assert "todo el año" in contenido or "anual" in contenido
    assert "Este autobús entra en el pueblo." in contenido  # leyenda (parada)
    assert "Pasa por Rivero de Posadas." in contenido  # leyenda (viaje)
    assert "P07" in contenido  # pendiente
    assert "sin datos" in contenido
    assert "sin servicio" in contenido
    assert "class='sin-datos'" in contenido
    assert "class='sin-servicio'" in contenido
    # hay cambios desde la versión publicada (la hora cambió)
    assert "08:10" in contenido and "08:15" in contenido
    assert "Primera versión." not in contenido


def test_cambios_con_texto_de_negocio_y_html_escapado(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo_root = _build_repo(tmp_path)
    obs = repo_root / DATASET / "observaciones.yaml"
    obs.write_text(
        obs.read_text(encoding="utf-8").replace(
            "Pasa por Rivero de Posadas.", "Pasa por <Rivero> & Posadas."
        ),
        encoding="utf-8",
    )
    assert _git(repo_root, "add", "tenants").returncode == 0
    assert _git(repo_root, "commit", "-q", "-m", "texto").returncode == 0

    assert _generar_para_repo(repo_root) == 0
    contenido = (repo_root / "revision" / SLUG / "horarios.html").read_text(encoding="utf-8")
    assert (
        "El texto de la observación «Pasa por Rivero de Posadas.» pasa a "
        "«Pasa por &lt;Rivero&gt; &amp; Posadas.»." in contenido
    )
    assert "pasa_por_rivero" not in contenido.split("Cambios desde la versión")[1][:600]


def test_main_primera_version_sin_tags(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo_root = tmp_path / "repo_sin_tags"
    horarios_dir = repo_root / DATASET
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
    (horarios_dir / "lineas" / "linea-prueba.yaml").write_text(LINEA_YAML, encoding="utf-8")
    _git(repo_root, "init", "-q", "-b", "main")
    _git(repo_root, "add", "tenants")
    _git(repo_root, "commit", "-q", "-m", "primera version")

    codigo = _generar_para_repo(repo_root)
    assert codigo == 0
    contenido = (repo_root / "revision" / SLUG / "horarios.html").read_text(encoding="utf-8")
    assert "Primera versión." in contenido


def test_main_solo_html_no_genera_pdf(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo_root = _build_repo(tmp_path)
    codigo = _generar_para_repo(repo_root, solo_html=True)
    assert codigo == 0
    assert (repo_root / "revision" / SLUG / "horarios.html").exists()
    assert not (repo_root / "revision" / SLUG / "horarios.pdf").exists()


def test_main_genera_pdf_si_no_se_pide_solo_html(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    try:
        import weasyprint  # type: ignore[import-untyped]  # noqa: F401
    except ImportError, OSError:  # sin el paquete, o sin Pango/cairo
        pytest.skip("WeasyPrint o Pango no disponibles")
    repo_root = _build_repo(tmp_path)
    codigo = _generar_para_repo(repo_root, solo_html=False)
    assert codigo == 0
    assert (repo_root / "revision" / SLUG / "horarios.pdf").exists()


def test_main_falla_si_weasyprint_no_esta_disponible(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo_root = _build_repo(tmp_path)

    import builtins

    real_import = builtins.__import__

    def _fake_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "weasyprint":
            raise ImportError("simulado: weasyprint no instalado")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _fake_import)

    codigo = revision.main([SLUG], repo_root=repo_root)
    assert codigo == 1
    assert (repo_root / "revision" / SLUG / "horarios.html").exists()
    assert not (repo_root / "revision" / SLUG / "horarios.pdf").exists()


def test_main_falla_si_horarios_no_valida(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo_root = _build_repo(tmp_path)
    # Se rompe horarios/ tras haber creado el repo: código de parada sin
    # definir en la última versión.
    (repo_root / DATASET / "lineas" / "linea-prueba.yaml").write_text(
        LINEA_YAML.replace("CCC", "ZZZ"), encoding="utf-8"
    )

    codigo = revision.main([SLUG, "--solo-html"], repo_root=repo_root)
    assert codigo == 1
    assert not (repo_root / "revision" / SLUG / "horarios.html").exists()


# ── Tablas por sentido, anchas y por línea ───────────────────
# Estos tests usan formato.validar() + revision.generar_html() directamente,
# sin repositorio git: no hace falta comparar dos versiones para comprobar
# cómo se pinta la versión actual.


def _construir_html(
    tmp_path: Path, paradas_fixture: str, lineas: dict[str, str], observaciones_extra: str = ""
) -> str:
    horarios_dir = tmp_path / "horarios"
    (horarios_dir / "lineas").mkdir(parents=True)
    (horarios_dir / "paradas.yaml").write_text(
        (FIXTURES / paradas_fixture).read_text(encoding="utf-8"), encoding="utf-8"
    )
    (horarios_dir / "observaciones.yaml").write_text(
        (FIXTURES / "observaciones_base.yaml").read_text(encoding="utf-8") + observaciones_extra,
        encoding="utf-8",
    )
    (horarios_dir / "calendario.yaml").write_text(
        (FIXTURES / "calendario_base.yaml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    for nombre, contenido in lineas.items():
        (horarios_dir / "lineas" / f"{nombre}.yaml").write_text(contenido, encoding="utf-8")
    resultado = validar_horarios(horarios_dir)
    assert resultado.errores == [], resultado.errores
    return revision.generar_html(modelo_de(resultado), None, None, None, "01/01/2026")


ADAMUZ_LINEA_YAML = """\
nombre: Línea Adamuz
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
      08:00  08:10  08:20
  - temporada: anual
    dias: lunes-viernes
    tabla: |
      CCC    BBB    AAA
      09:00  09:10  09:20
pendientes: []
"""


def test_dos_tablas_misma_temporada_y_dias_se_pintan_por_separado(tmp_path: Path) -> None:
    html_doc = _construir_html(tmp_path, "paradas_base.yaml", {"linea-adamuz": ADAMUZ_LINEA_YAML})
    assert html_doc.count("<table class='horario corta'>") == 2
    assert "<th>Pueblo A</th><th>Pueblo B</th><th>Pueblo C</th>" in html_doc
    assert "<th>Pueblo C</th><th>Pueblo B</th><th>Pueblo A</th>" in html_doc


CODIGOS_ANCHA = [
    "AAA",
    "BBB",
    "CCC",
    "DDD",
    "EEE",
    "FFF",
    "GGG",
    "HHH",
    "III",
    "JJJ",
    "KKK",
    "LLL",
    "MMM",
]


def _fila_ancha(inicio_minutos: int) -> str:
    valores = []
    minutos = inicio_minutos
    for _ in CODIGOS_ANCHA:
        valores.append(f"{minutos // 60:02d}:{minutos % 60:02d}")
        minutos += 5
    return "  ".join(valores)


def _linea_ancha_yaml(n_filas: int) -> str:
    cabecera = "  ".join(CODIGOS_ANCHA)
    filas = [_fila_ancha(8 * 60 + 30 * i) for i in range(n_filas)]
    tabla_txt = "\n      ".join([cabecera] + filas)
    return f"""\
nombre: Línea Ancha
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
      {tabla_txt}
pendientes: []
"""


def test_tabla_ancha_se_traspone_y_reparte_en_bloques(tmp_path: Path) -> None:
    html_doc = _construir_html(
        tmp_path,
        "paradas_ancha.yaml",
        {"linea-ancha": _linea_ancha_yaml(9)},
    )
    assert "transpuesta" in html_doc
    for codigo in CODIGOS_ANCHA:
        assert f"Parada {codigo}" in html_doc
    # 9 viajes repartidos en bloques de 8 -> dos tablas trasponidas.
    assert html_doc.count("class='horario transpuesta corta'") == 2


def test_telefono_se_sustituye_en_la_leyenda(tmp_path: Path) -> None:
    linea_yaml = """\
nombre: Línea a demanda
telefono_demanda: "957 42 90 30"
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
      08:00D 08:10  08:20
pendientes: []
"""
    html_doc = _construir_html(tmp_path, "paradas_base.yaml", {"linea-demanda": linea_yaml})
    assert "957 42 90 30" in html_doc
    assert "{telefono}" not in html_doc


def test_avisos_de_linea_y_no_circula_se_pintan(tmp_path: Path) -> None:
    linea_yaml = """\
nombre: Línea con avisos
avisos: [hora_aproximada]
no_circula: [agosto]
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
pendientes: []
"""
    html_doc = _construir_html(tmp_path, "paradas_base.yaml", {"linea-avisos": linea_yaml})
    assert "Avisos de la línea" in html_doc
    assert "Horarios de paso aproximados." in html_doc
    assert "No circula en: agosto" in html_doc


def test_seccion_lineas_en_el_bot_muestra_titulo_descripcion_y_pueblos(tmp_path: Path) -> None:
    linea_yaml = """\
nombre: Línea de prueba con nombre largo
nombre_corto: Línea corta
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
      08:00  08:10  08:20
pendientes: []
"""
    html_doc = _construir_html(
        tmp_path, "paradas_con_pendientes.yaml", {"linea-prueba": linea_yaml}
    )
    assert "Así aparecen las líneas en el bot" in html_doc
    assert "Pueblos, paradas y zonas" not in html_doc
    assert "zona" not in html_doc.lower()
    idx = html_doc.index("Así aparecen las líneas en el bot")
    seccion = html_doc[idx:]
    # título que ve el cliente + descripción exacta de la fila de la lista
    assert "<h3>Línea corta</h3>" in seccion
    assert "En el bot: Línea de prueba con nombre largo · 3 pueblos" in seccion
    for pueblo in ("Pueblo A", "Pueblo B", "Pueblo C"):
        assert pueblo in seccion
    # Cabeza del Buey no la usa ninguna línea: lista aparte
    idx_aparte = seccion.index("Localidades que ninguna línea usa")
    assert "Cabeza del Buey" in seccion[idx_aparte:]


def test_seccion_lineas_en_el_bot_sin_lista_aparte_si_todas_se_usan(tmp_path: Path) -> None:
    html_doc = _construir_html(tmp_path, "paradas_base.yaml", {"linea-prueba": LINEA_YAML})
    assert "Localidades que ninguna línea usa" not in html_doc


def test_html_real_seccion_lineas_con_los_4_nombres_cortos() -> None:
    html_doc = _html_real()
    assert "zona" not in html_doc.lower().replace("zona horaria", "")
    idx = html_doc.index("Así aparecen las líneas en el bot")
    seccion = html_doc[idx:]
    for corto in (
        "Adamuz – Córdoba",
        "F. Carreteros – Córdoba",
        "Estación AVE Villanueva",
        "Santa Eufemia-Villaralto",
    ):
        assert f"<h3>{corto}</h3>" in seccion
    assert "En el bot: Fuente Carreteros – Córdoba · 7 pueblos" in seccion
    # Cabeza del Buey solo está en Belalcázar – Córdoba
    idx_bel = seccion.index("<h3>Belalcázar – Córdoba</h3>")
    assert "Cabeza del Buey" in seccion[idx_bel : idx_bel + 1500]


# ── Sección "Calendario" y pendientes del calendario (P03e, P03g, P12b) ─────


def _html_real() -> str:
    resultado = validar_horarios(FIXTURES / "horarios_real")
    assert resultado.errores == []
    return revision.generar_html(modelo_de(resultado), None, None, None, "01/01/2026")


def test_html_real_tiene_seccion_calendario() -> None:
    html_doc = _html_real()
    assert "<h2>Calendario</h2>" in html_doc
    seccion = html_doc[html_doc.index("<h2>Calendario</h2>") :]
    seccion = seccion[: seccion.index("</body>")]
    # días sin servicio en ninguna línea
    assert "<li>25/12</li>" in seccion and "<li>01/01</li>" in seccion
    # festivos generales
    assert "12/10/2026 — Fiesta Nacional" in seccion
    # festivos locales con las líneas que los aplican
    assert "Córdoba" in seccion
    assert "08/09/2026 — Virgen de la Fuensanta" in seccion
    assert "24/10/2026 — San Rafael" in seccion
    for nombre in ("Pozoblanco", "Adamuz", "Badajoz"):
        assert nombre in seccion
    # no vendibles, con el texto propuesto del bot
    assert "Trayectos que no se venden" in seccion
    assert (
        "Entre Alcolea y Córdoba no vendemos billetes, en ninguno de los dos "
        "sentidos. Puedes elegir otro destino."
    ) in seccion
    assert "Campus de Rabanales" in seccion


def test_html_real_sin_anexo_ni_pendientes_en_portada() -> None:
    # El anexo de preguntas pendientes y la línea "Pendientes abiertos" de la
    # portada se quitaron: ya no hay dudas abiertas con negocio.
    html_doc = _html_real()
    assert "Anexo" not in html_doc
    assert "Pendientes abiertos" not in html_doc


def test_seccion_calendario_sin_festivos_locales_ni_no_vendibles(tmp_path: Path) -> None:
    html_doc = _construir_html(tmp_path, "paradas_base.yaml", {"linea-prueba": ADAMUZ_LINEA_YAML})
    seccion = html_doc[html_doc.index("<h2>Calendario</h2>") :]
    assert "Días sin servicio en ninguna línea" in seccion
    assert seccion.count("<p>Ninguno.</p>") == 3  # sin servicio, locales, no vendibles


# ── Ciclo C1: llegada/salida y "mismo autobús que" ───────────────────────────


def _html_cicloc() -> str:
    resultado = validar_horarios(FIXTURES / "horarios_cicloC")
    assert resultado.errores == [], resultado.errores
    return revision.generar_html(modelo_de(resultado), None, None, None, "01/01/2026")


def test_celda_con_espera_muestra_llega_y_sale() -> None:
    html_doc = _html_cicloc()
    assert "<td>llega 11:55 · sale 12:30</td>" in html_doc
    # una celda simple sigue mostrando solo la hora
    assert "<td>11:40</td>" in html_doc


def test_celda_con_espera_y_letra_pone_la_letra_al_final() -> None:
    modelo = modelo_de(validar_horarios(FIXTURES / "horarios_cicloC"))
    paso = modelo.lineas["larga"].viajes[0].pasos[-2]  # PVN 12:50A
    assert revision._celda_paso(modelo, paso) == "<td>12:50A</td>"


def test_mismo_autobus_que_nombra_la_otra_linea_dias_y_sentido() -> None:
    html_doc = _html_cicloc()
    assert (
        "mismo autobús que: Peñarroya – Córdoba "
        "(lunes a viernes, de Córdoba a Peñarroya)" in html_doc
    )
    assert (
        "mismo autobús que: Los Blázquez – Córdoba "
        "(lunes a viernes, de Córdoba a Los Blázquez)" in html_doc
    )


def test_mismo_autobus_de_la_misma_linea_cita_la_otra_tabla_no_la_propia() -> None:
    html_doc = _html_cicloc()
    frases = [f.split("</p>")[0] for f in html_doc.split("<p class='mismo-bus'>")[1:]]
    assert len(frases) == 5  # larga, corta (2 tablas) y paso (2 tablas)
    con_corta = [
        f for f in frases if "Peñarroya – Córdoba (lunes a viernes, de Córdoba a El Porvenir)" in f
    ]
    # tabla lunes a jueves de paso: cita corta y la tabla de viernes, no la suya
    lj = next(f for f in con_corta if "Paso – Córdoba (viernes" in f)
    assert "Paso – Córdoba (lunes a jueves" not in lj
    # tabla de viernes de paso: cita corta y la de lunes a jueves, no la suya
    v = next(f for f in con_corta if "Paso – Córdoba (lunes a jueves" in f)
    assert "Paso – Córdoba (viernes" not in v


def test_sin_bus_no_hay_frase_de_mismo_autobus(tmp_path: Path) -> None:
    html_doc = _construir_html(tmp_path, "paradas_base.yaml", {"adamuz": ADAMUZ_LINEA_YAML})
    assert "mismo-bus'>" not in html_doc
    assert "mismo autobús que" not in html_doc


# ── Sección "Localidades sin hora de paso" (ciclo C2, P15/P32) ─────────────


def test_html_pendientes_muestra_localidades_y_viajes() -> None:
    resultado = validar_horarios(FIXTURES / "horarios_pendientes")
    assert resultado.errores == []
    html_doc = revision.generar_html(modelo_de(resultado), None, None, None, "01/01/2026")
    assert "<h2>Localidades sin hora de paso</h2>" in html_doc
    seccion = html_doc[html_doc.index("<h2>Localidades sin hora de paso</h2>") :]
    seccion = seccion[: seccion.index("<h2>Calendario</h2>")]
    assert "Aldea A" in seccion and "Aldea Bonita" in seccion
    assert "P32" in seccion
    assert "Consultar en su lugar: Pueblo A" in seccion
    assert "Consultar en su lugar: Pueblo B" in seccion
    assert "a unos 4 minutos" in seccion and "a unos 7 minutos" in seccion
    # viajes relacionados: la primera hora de cada viaje con el aviso
    assert "Pueblo A – Pueblo C" in seccion
    assert "<td>08:00</td>" in seccion and "<td>10:00</td>" in seccion
    assert "<td>15:00</td>" not in seccion
    # antes del calendario
    assert html_doc.index("Localidades sin hora de paso") < html_doc.index("<h2>Calendario</h2>")


def test_html_pendientes_sin_viajes_declarados(tmp_path: Path) -> None:
    import shutil

    destino = tmp_path / "h"
    shutil.copytree(FIXTURES / "horarios_pendientes", destino)
    linea = destino / "lineas" / "linea.yaml"
    linea.write_text(
        linea.read_text(encoding="utf-8")
        .replace("  | pasa_por_aldea_a", "")
        .replace("  | para_en_aldea_b", ""),
        encoding="utf-8",
    )
    resultado = validar_horarios(destino)
    assert resultado.errores == []
    html_doc = revision.generar_html(modelo_de(resultado), None, None, None, "01/01/2026")
    assert html_doc.count("ningún viaje declarado") == 2


def test_html_real_ya_no_tiene_seccion_de_localidades_sin_hora_de_paso() -> None:
    html_doc = _html_real()
    assert "Localidades sin hora de paso" not in html_doc


def test_html_real_hornachuelos_tiene_columnas_rivero_y_los_mochos() -> None:
    html_doc = _html_real()
    inicio = html_doc.index("<h2>Hornachuelos – Córdoba</h2>")
    seccion = html_doc[inicio : html_doc.index("<h2>", inicio + 10)]
    assert "Rivero de Posadas" in seccion and "Los Mochos" in seccion


def test_html_real_badajoz_tiene_temporada_de_agosto() -> None:
    html_doc = _html_real()
    inicio = html_doc.index("<h2>Badajoz – Córdoba</h2>")
    seccion = html_doc[inicio : html_doc.index("<h2>", inicio + 10)]
    assert "agosto" in seccion.lower()


def test_html_real_pueblos_con_el_nuevo_formato() -> None:
    html_doc = _html_real()
    pueblos = html_doc[html_doc.index("<h2>Así aparecen las líneas en el bot</h2>") :]
    assert "Cada pueblo es lo que elige el cliente; si tiene más de una" in pueblos
    assert "<li>Azuaga " in pueblos or "<li>Azuaga</li>" in pueblos
    assert "Azuaga — " not in pueblos
    assert "Villanueva del Rey — para en: Villanueva del Rey (cruce, gasolinera) o" in pueblos
    assert "Villanueva del Rey (pueblo)" in pueblos


def test_html_real_tiene_15_secciones_de_linea() -> None:
    html_doc = _html_real()
    inicio = html_doc.index("<h2>Cambios desde la versión publicada</h2>")
    fin = html_doc.index("<h2>Así aparecen las líneas en el bot</h2>")
    bloque = html_doc[inicio:fin]
    assert bloque.count("<h2>") - 1 == 15
    for nombre in ("Peñarroya – Córdoba", "Los Blázquez", "Hornachuelos – Córdoba"):
        assert f"<h2>{nombre}</h2>" in bloque


_OBS_EXTRA = """
otra_nota:
  tipo: aviso
  ambitos: [viaje]
  texto: "Otra nota."
"""

_LINEA_NOTAS = """\
nombre: Línea notas
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
      08:00  08:10  08:20
      09:00  09:10  09:20  | pasa_por_rivero
      10:00  10:10  10:20  | pasa_por_rivero otra_nota
pendientes: []
"""


def test_notas_de_viaje_sin_letra_se_numeran(tmp_path: Path) -> None:
    html_ = _construir_html(tmp_path, "paradas_base.yaml", {"l": _LINEA_NOTAS}, _OBS_EXTRA)
    assert "<th>Notas</th>" in html_
    assert "<td></td></tr>" in html_  # fila sin notas
    assert "<td>[1]</td></tr>" in html_
    assert "<td>[1] [2]</td></tr>" in html_
    assert "[1] Pasa por Rivero de Posadas." in html_
    assert "[2] Otra nota." in html_


def test_tabla_sin_notas_no_tiene_columna_notas(tmp_path: Path) -> None:
    html_ = _construir_html(tmp_path, "paradas_base.yaml", {"l": ADAMUZ_LINEA_YAML})
    assert "<th>Notas</th>" not in html_


def test_pendientes_muestran_dias_en_palabras(tmp_path: Path) -> None:
    import shutil

    destino = tmp_path / "h"
    shutil.copytree(FIXTURES / "horarios_pendientes", destino)
    linea = destino / "lineas" / "linea.yaml"
    texto = linea.read_text(encoding="utf-8").replace("sabado: sin_servicio", "sabado: horario")
    texto = texto.replace(
        "\npendientes: []",
        """
  - temporada: anual
    dias: sabado
    tabla: |
      PAA    PBB    PCC
      09:00  09:30  10:00  | pasa_por_aldea_a

pendientes: []""",
    )
    linea.write_text(texto, encoding="utf-8")
    resultado = validar_horarios(destino)
    assert resultado.errores == []
    html_ = revision.generar_html(modelo_de(resultado), None, None, None, "01/01/2026")
    inicio = html_.index("Localidades sin hora de paso")
    seccion = html_[inicio:]
    assert "sábado" in seccion
    assert "lunes a viernes" in seccion
    assert "<td>sabado</td>" not in seccion
    assert "<td>lunes-viernes</td>" not in seccion
