"""The bus timetable tools with the TENANT parameter (design.md §10.1, §16.3), on a
throwaway git repository in tmp_path with the frozen real dataset."""

from __future__ import annotations

import shutil
import subprocess
from datetime import date
from pathlib import Path

import pytest

from tools import bus_formatear, bus_publicar, bus_revision, bus_validar

REAL = Path(__file__).parents[2] / "src" / "packs" / "bus" / "tests" / "fixtures" / "horarios_real"
SLUG = "autocares-ss"
DATASET = Path("tenants") / SLUG / "datasets" / "timetable"
# Una fila de pozoblanco-cordoba.yaml (se cambia solo su primera aparición).
FILA = "      20:00  20:30  20:35D  21:00  21:10  21:15  21:45C"


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-c", "user.email=test@example.com", "-c", "user.name=Test", *args],
        cwd=repo,
        capture_output=True,
        text=True,
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    shutil.copytree(REAL, root / DATASET)
    assert _git(root, "init", "-q", "-b", "main").returncode == 0
    assert _git(root, "add", "tenants").returncode == 0
    assert _git(root, "commit", "-q", "-m", "datos").returncode == 0
    return root


def _cambiar_una_hora(repo: Path) -> None:
    linea = repo / DATASET / "lineas" / "pozoblanco-cordoba.yaml"
    texto = linea.read_text(encoding="utf-8")
    assert FILA in texto
    linea.write_text(texto.replace(FILA, FILA.replace("20:00", "20:05", 1), 1), encoding="utf-8")


def _tags(repo: Path) -> list[str]:
    return _git(repo, "tag", "--list").stdout.split()


# ── Parámetro TENANT ──────────────────────────────────────────────────────


@pytest.mark.parametrize("main", [bus_validar.main, bus_formatear.main, bus_publicar.main])
def test_el_tenant_es_obligatorio_y_debe_existir(
    main: object, repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert callable(main)
    assert main([], repo_root=repo) == 2
    assert "TENANT=<slug>" in capsys.readouterr().out
    assert main(["no-existe"], repo_root=repo) == 2
    assert "no tiene dataset de horarios" in capsys.readouterr().out
    for malo in ("../fuera", "-x", f"{SLUG}\n"):
        assert main([malo], repo_root=repo) == 2
        assert "slug de tenant inválido" in capsys.readouterr().out


def test_validar_el_dataset_real(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert bus_validar.main([SLUG], repo_root=repo) == 0
    salida = capsys.readouterr().out
    assert "Sin errores." in salida and "AVISOS (" in salida


def test_validar_un_dataset_roto(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    linea = repo / DATASET / "lineas" / "pozoblanco-cordoba.yaml"
    texto = linea.read_text(encoding="utf-8")
    # La hora de salida pasa a ser posterior a la siguiente: horas que retroceden.
    linea.write_text(texto.replace(FILA, FILA.replace("20:00", "20:45", 1), 1), encoding="utf-8")
    assert bus_validar.main([SLUG], repo_root=repo) == 1
    assert "ERRORES (" in capsys.readouterr().out


def test_formatear_el_dataset_real_no_cambia_nada(repo: Path) -> None:
    assert bus_formatear.main([SLUG], repo_root=repo) == 0
    assert _git(repo, "status", "--porcelain").stdout == ""


# ── bus-publicar ──────────────────────────────────────────────────────────


def test_publicar_crea_el_tag_del_dia(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert bus_publicar.main([SLUG], repo_root=repo, hoy=date(2026, 10, 22)) == 0
    assert _tags(repo) == ["datos/autocares-ss/2026-10-22"]
    assert "git push origin datos/autocares-ss/2026-10-22" in capsys.readouterr().out
    # Repetirlo el mismo día sobre el mismo commit no hace nada.
    assert bus_publicar.main([SLUG], repo_root=repo, hoy=date(2026, 10, 22)) == 0


def test_publicar_no_mueve_un_tag_existente(repo: Path) -> None:
    assert bus_publicar.main([SLUG], repo_root=repo, hoy=date(2026, 10, 22)) == 0
    _cambiar_una_hora(repo)
    _git(repo, "commit", "-qam", "cambio")
    assert bus_publicar.main([SLUG], repo_root=repo, hoy=date(2026, 10, 22)) == 1
    assert bus_publicar.main([SLUG], repo_root=repo, hoy=date(2026, 10, 23)) == 0
    assert _tags(repo) == ["datos/autocares-ss/2026-10-22", "datos/autocares-ss/2026-10-23"]


def test_publicar_exige_el_dataset_confirmado(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _cambiar_una_hora(repo)
    assert bus_publicar.main([SLUG], repo_root=repo, hoy=date(2026, 10, 22)) == 1
    assert "cambios sin confirmar" in capsys.readouterr().out
    assert _tags(repo) == []


def test_publicar_exige_un_dataset_valido(repo: Path) -> None:
    (repo / DATASET / "paradas.yaml").write_text("localidades: [\n", encoding="utf-8")
    _git(repo, "commit", "-qam", "roto")
    assert bus_publicar.main([SLUG], repo_root=repo, hoy=date(2026, 10, 22)) == 1
    assert _tags(repo) == []


# ── bus-revision: cambios desde el último tag ─────────────────────────────


def _hay_weasyprint() -> bool:
    try:
        import weasyprint  # type: ignore[import-untyped]  # noqa: F401
    except ImportError, OSError:  # sin el paquete, o sin Pango/cairo
        return False
    return True


def test_revision_compara_con_el_ultimo_tag_del_tenant(repo: Path) -> None:
    assert bus_publicar.main([SLUG], repo_root=repo, hoy=date(2026, 10, 1)) == 0
    # Un tag de otro tenant no cuenta.
    _git(repo, "tag", "datos/otro/2026-10-20")
    _cambiar_una_hora(repo)
    _git(repo, "commit", "-qam", "cambio de hora")

    assert bus_revision.main([SLUG, "--solo-html"], repo_root=repo) == 0
    html = (repo / "revision" / SLUG / "horarios.html").read_text(encoding="utf-8")
    assert "Versión: datos/autocares-ss/2026-10-01" in html
    cambios = html.split("Cambios desde la versión publicada")[1].split("<h2")[0]
    assert "20:00" in cambios and "20:05" in cambios


@pytest.mark.skipif(not _hay_weasyprint(), reason="WeasyPrint o Pango no disponibles")
def test_revision_genera_el_pdf_de_los_datos_reales(repo: Path) -> None:
    assert bus_publicar.main([SLUG], repo_root=repo, hoy=date(2026, 10, 1)) == 0
    _cambiar_una_hora(repo)
    _git(repo, "commit", "-qam", "cambio de hora")
    assert bus_revision.main([SLUG], repo_root=repo) == 0
    pdf = repo / "revision" / SLUG / "horarios.pdf"
    assert pdf.read_bytes().startswith(b"%PDF")
