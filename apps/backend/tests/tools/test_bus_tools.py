"""Bus tools work on ignored directory exports, without a git repository."""

import shutil
from pathlib import Path

import pytest

from tools import bus_formatear, bus_revision, bus_validar

REAL = Path(__file__).parent.parent / "packs" / "bus" / "fixtures" / "horarios_real"
SLUG = "autocares-ss"
DATASET = Path("datos") / SLUG / "timetable"
ROW = "      20:00  20:30  20:35D  21:00  21:10  21:15  21:45C"


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    shutil.copytree(REAL, root / DATASET)
    return root


def change_time(repo: Path) -> None:
    line = repo / DATASET / "lineas/pozoblanco-cordoba.yaml"
    text = line.read_text(encoding="utf-8")
    assert ROW in text
    line.write_text(text.replace(ROW, ROW.replace("20:00", "20:05", 1), 1), encoding="utf-8")


@pytest.mark.parametrize("main", [bus_validar.main, bus_formatear.main])
def test_tenant_is_required_and_must_exist(
    main: object, repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert callable(main)
    assert main([], repo_root=repo) == 2
    assert "TENANT=<slug>" in capsys.readouterr().out
    assert main(["no-existe"], repo_root=repo) == 2
    assert "no tiene dataset de horarios" in capsys.readouterr().out
    for invalid in ("../fuera", "-x", f"{SLUG}\n"):
        assert main([invalid], repo_root=repo) == 2
        assert "slug de tenant inválido" in capsys.readouterr().out


def test_validate_real_dataset(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert bus_validar.main([SLUG], repo_root=repo) == 0
    output = capsys.readouterr().out
    assert "Sin errores." in output and "AVISOS (" in output


def test_validate_broken_dataset(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    line = repo / DATASET / "lineas/pozoblanco-cordoba.yaml"
    text = line.read_text(encoding="utf-8")
    line.write_text(text.replace(ROW, ROW.replace("20:00", "20:45", 1), 1), encoding="utf-8")
    assert bus_validar.main([SLUG], repo_root=repo) == 1
    assert "ERRORES (" in capsys.readouterr().out


def test_format_real_dataset_keeps_content(repo: Path) -> None:
    before = {
        path.relative_to(repo / DATASET): path.read_text()
        for path in (repo / DATASET).rglob("*")
        if path.is_file()
    }
    assert bus_formatear.main([SLUG], repo_root=repo) == 0
    after = {
        path.relative_to(repo / DATASET): path.read_text()
        for path in (repo / DATASET).rglob("*")
        if path.is_file()
    }
    assert before == after


def test_revision_compares_published_directory(repo: Path) -> None:
    shutil.copytree(repo / DATASET, repo / "datos" / SLUG / ".publicado/timetable")
    change_time(repo)
    assert bus_revision.main([SLUG, "--solo-html"], repo_root=repo) == 0
    html = (repo / "revision" / SLUG / "horarios.html").read_text(encoding="utf-8")
    assert "Versión: copia publicada" in html
    changes = html.split("Cambios desde la versión publicada")[1].split("<h2")[0]
    assert "20:00" in changes and "20:05" in changes


def test_revision_generates_real_pdf(repo: Path) -> None:
    shutil.copytree(repo / DATASET, repo / "datos" / SLUG / ".publicado/timetable")
    change_time(repo)
    assert bus_revision.main([SLUG], repo_root=repo) == 0
    assert (repo / "revision" / SLUG / "horarios.pdf").read_bytes().startswith(b"%PDF")
