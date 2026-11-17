"""`manage.py dataset_library push/list/current-sha` (C21, ADR-013)."""

import io
import json
from pathlib import Path

import pytest
import yaml
from django.core.management import call_command
from django.core.management.base import CommandError

from autobot.tenancy import dataset_library
from autobot.tenancy.registry import source_from_dir
from packs.registry import PACKS as REGISTERED

pytestmark = pytest.mark.django_db(transaction=True, databases=["default", "owner"])


def command(name: str, *args: str) -> str:
    output = io.StringIO()
    call_command(name, *args, stdout=output)
    return output.getvalue()


def write_bus_dataset(directory: Path) -> None:
    template = REGISTERED["bus"].template
    assert template is not None
    source = source_from_dir(template)
    for relpath, content in source.datasets["timetable"].items():
        target = directory / relpath
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")


def test_push_from_a_directory_creates_a_version(tmp_path: Path) -> None:
    write_bus_dataset(tmp_path)
    output = command(
        "dataset_library", "push", "bus", "timetable", "prueba", str(tmp_path), "--comment", "c"
    )
    assert "v1" in output
    assert dataset_library.latest("bus", "timetable", "prueba") is not None


def test_push_again_unchanged_reports_no_change(tmp_path: Path) -> None:
    write_bus_dataset(tmp_path)
    command(
        "dataset_library", "push", "bus", "timetable", "prueba", str(tmp_path), "--comment", "c"
    )
    output = command(
        "dataset_library", "push", "bus", "timetable", "prueba", str(tmp_path), "--comment", "c2"
    )
    assert "sin cambios" in output


def test_push_rejects_a_stale_base_sha(tmp_path: Path) -> None:
    write_bus_dataset(tmp_path)
    command("dataset_library", "push", "bus", "timetable", "x", str(tmp_path), "--comment", "c")
    (tmp_path / "note.txt").write_text("extra", encoding="utf-8")
    with pytest.raises(CommandError):
        command(
            "dataset_library",
            "push",
            "bus",
            "timetable",
            "x",
            str(tmp_path),
            "--comment",
            "c2",
            "--base-sha",
            "not-the-real-sha",
        )


def test_push_rejects_invalid_data(tmp_path: Path) -> None:
    (tmp_path / "calendario.yaml").write_text(yaml.safe_dump({"festivos": {}}), encoding="utf-8")
    with pytest.raises(CommandError):
        command(
            "dataset_library",
            "push",
            "bus",
            "timetable",
            "broken",
            str(tmp_path),
            "--comment",
            "c",
        )


def test_dry_run_reports_without_writing(tmp_path: Path) -> None:
    write_bus_dataset(tmp_path)
    output = command(
        "dataset_library",
        "push",
        "bus",
        "timetable",
        "prueba",
        str(tmp_path),
        "--comment",
        "c",
        "--dry-run",
    )
    assert "cambiaría" in output
    assert dataset_library.latest("bus", "timetable", "prueba") is None


def test_current_sha_is_empty_for_an_unknown_entry() -> None:
    assert command("dataset_library", "current-sha", "bus", "timetable", "nope") == "SHA:\n"


def test_current_sha_matches_the_pushed_entry(tmp_path: Path) -> None:
    write_bus_dataset(tmp_path)
    command(
        "dataset_library", "push", "bus", "timetable", "prueba", str(tmp_path), "--comment", "c"
    )
    entry = dataset_library.latest("bus", "timetable", "prueba")
    assert entry is not None
    assert (
        command("dataset_library", "current-sha", "bus", "timetable", "prueba").strip()
        == f"SHA:{entry.sha256}"
    )


def test_pull_writes_the_entrys_files_to_a_directory(tmp_path: Path) -> None:
    source = tmp_path / "source"
    write_bus_dataset(source)
    command("dataset_library", "push", "bus", "timetable", "prueba", str(source), "--comment", "c")
    destination = tmp_path / "dest"
    output = command("dataset_library", "pull", "bus", "timetable", "prueba", str(destination))
    assert "v1" in output
    assert (destination / "calendario.yaml").read_text(encoding="utf-8") == (
        source / "calendario.yaml"
    ).read_text(encoding="utf-8")


def test_pull_an_unknown_entry_fails_clearly(tmp_path: Path) -> None:
    with pytest.raises(CommandError):
        command("dataset_library", "pull", "bus", "timetable", "nope", str(tmp_path))


def test_list_reports_name_version_and_summary_never_files(tmp_path: Path) -> None:
    write_bus_dataset(tmp_path)
    command(
        "dataset_library", "push", "bus", "timetable", "prueba", str(tmp_path), "--comment", "c"
    )
    output = command("dataset_library", "list", "bus", "timetable")
    (entry,) = json.loads(output)
    assert entry["name"] == "prueba" and entry["version"] == 1
    assert entry["summary"]["pueblos"]
    assert "files" not in entry
