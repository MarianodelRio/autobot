"""`tools.bus.library`: local database round-trips and SSH doubles for the dataset
library (ADR-013, C21)."""

import os
import shlex
import shutil
import tarfile
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import quote

import pytest
from django.conf import settings

from autobot.tenancy import dataset_library
from packs.registry import PACKS
from tools.bus import library as bus_library

PACK = "bus"
DATASET = "timetable"
pytestmark = pytest.mark.django_db(transaction=True, databases=["default", "owner"])


@pytest.fixture
def database(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    for alias, variable in (("owner", "DB_OWNER_URL"), ("default", "DB_APP_URL")):
        db = settings.DATABASES[alias]
        monkeypatch.setenv(
            variable,
            f"postgres://{quote(db['USER'])}:{quote(db['PASSWORD'])}@{db['HOST']}:{db['PORT']}/{quote(db['NAME'])}",
        )
    monkeypatch.setenv("SENTRY_DSN", "")
    monkeypatch.setenv("ENVIRONMENT", "local")
    monkeypatch.delenv("PROD", raising=False)
    yield


def seed_entry(name: str) -> None:
    template = PACKS["bus"].template
    assert template is not None
    from autobot.tenancy.registry import source_from_dir

    files = source_from_dir(template).datasets["timetable"]
    dataset_library.push(
        pack=PACK,
        dataset=DATASET,
        name=name,
        files=files,
        author="test",
        comment="c",
        base_sha=None,
    )


def test_local_pull_push_and_no_change(tmp_path: Path, database: None) -> None:
    seed_entry("prueba")
    assert bus_library.main(["pull", "--nombre", "prueba", "--dir", str(tmp_path / "w")]) == 0
    working = tmp_path / "w"
    assert (working / "calendario.yaml").is_file()
    (working / "note.txt").write_text("nota revisada")
    args = ["push", "--nombre", "prueba", "--dir", str(working), "--comment", "Nota"]
    assert bus_library.main(args) == 0
    entry = dataset_library.latest(PACK, DATASET, "prueba")
    assert entry is not None and entry.version == 2 and entry.files["note.txt"] == "nota revisada"
    assert bus_library.main(args) == 0  # same content again: no new version
    entry = dataset_library.latest(PACK, DATASET, "prueba")
    assert entry is not None and entry.version == 2


def test_invalid_data_is_rejected_without_pushing(tmp_path: Path, database: None) -> None:
    seed_entry("prueba")
    working = tmp_path / "w"
    working.mkdir()
    (working / "paradas.yaml").write_text("invalid: [")
    assert (
        bus_library.main(["push", "--nombre", "prueba", "--dir", str(working), "--comment", "Bad"])
        == 1
    )
    entry = dataset_library.latest(PACK, DATASET, "prueba")
    assert entry is not None and entry.version == 1


def fake_ssh(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    template = PACKS["bus"].template
    assert template is not None
    source = tmp_path / "source.tar.gz"
    with tarfile.open(source, mode="w:gz") as output:
        output.add(template / "datasets/timetable", arcname=".")
    binary = tmp_path / "ssh"
    binary.write_text(
        "#!/usr/bin/env bash\n"
        'printf \'%s\\n\' "$2" >"$SSH_ARGS"\n'
        'if [[ $2 == *" pull "* ]]; then cat "$SSH_SOURCE";\n'
        'elif [[ $2 == *" current-sha "* ]]; then echo "SHA:deadbeef";\n'
        'elif [[ $2 == *" --dry-run"* ]]; then cat >/dev/null; echo "cambiaría (entrada nueva)";\n'
        'else cat >"$SSH_CAPTURE"; echo "Subido timetable v2"; fi\n'
    )
    binary.chmod(0o755)
    monkeypatch.setenv("PATH", f"{tmp_path}:{os.environ['PATH']}")
    monkeypatch.setenv("HOST", "fake-host")
    monkeypatch.setenv("SSH_SOURCE", str(source))
    monkeypatch.setenv("SSH_ARGS", str(tmp_path / "args"))
    monkeypatch.setenv("SSH_CAPTURE", str(tmp_path / "captured.tar.gz"))


def test_remote_push_quotes_the_comment_and_uses_base_sha(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_ssh(tmp_path, monkeypatch)
    working = tmp_path / "w"
    template = PACKS["bus"].template
    assert template is not None
    shutil.copytree(template / "datasets/timetable", working)
    comment = 'Invierno "revisado"; $(do-not-execute)'
    assert (
        bus_library.main(
            ["push", "--nombre", "prueba", "--dir", str(working), "--comment", comment, "--prod"]
        )
        == 0
    )
    calls = (tmp_path / "args").read_text().splitlines()
    # The real push (last call) carries --base-sha and the exact comment, untouched
    # by the shell despite the quotes and the `$(...)`.
    assert shlex.split(calls[-1])[-4:] == ["--comment", comment, "--base-sha", "deadbeef"]
    with tarfile.open(tmp_path / "captured.tar.gz", mode="r:gz") as uploaded:
        assert "./calendario.yaml" in uploaded.getnames()


def test_remote_pull_streams_the_tar_without_log_noise(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_ssh(tmp_path, monkeypatch)
    destination = tmp_path / "out"
    assert (
        bus_library.main(["pull", "--nombre", "prueba", "--dir", str(destination), "--prod"]) == 0
    )
    assert (destination / "calendario.yaml").is_file()
