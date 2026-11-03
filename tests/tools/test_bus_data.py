"""Local database round-trips and SSH doubles for timetable publication."""

import os
import shlex
import subprocess
import tarfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from urllib.parse import quote

import pytest
from django.conf import settings
from django.core.management import call_command

from autobot.tenancy.models import TenantDatasetVersion
from packs.registry import PACKS
from tools import bus_data

SLUG = "demo-autobuses"
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
    call_command("seed_demos")
    yield


def test_local_download_publish_and_no_change(tmp_path: Path, database: None) -> None:
    working = tmp_path / "datos" / SLUG / "timetable"
    published = tmp_path / "datos" / SLUG / ".publicado/timetable"
    for folder in (working, published):
        folder.mkdir(parents=True)
        (folder / "stale.txt").write_text("stale")
    assert bus_data.main(["download", "--tenant", SLUG], repo_root=tmp_path) == 0
    assert not (working / "stale.txt").exists() and not (published / "stale.txt").exists()
    (working / "note.txt").write_text("published note")
    args = ["publish", "--tenant", SLUG, "--comment", "Reviewed note"]
    assert bus_data.main(args, repo_root=tmp_path) == 0
    assert (published / "note.txt").read_text() == "published note"
    row = TenantDatasetVersion.objects.using("owner").filter(tenant__slug=SLUG).latest("version")
    assert row.version == 2 and row.files["note.txt"] == "published note"
    assert bus_data.main(args, repo_root=tmp_path) == 0
    assert TenantDatasetVersion.objects.using("owner").filter(tenant__slug=SLUG).count() == 2


def test_invalid_data_and_missing_comment_do_not_publish(tmp_path: Path, database: None) -> None:
    assert bus_data.main(["download", "--tenant", SLUG], repo_root=tmp_path) == 0
    working = tmp_path / "datos" / SLUG / "timetable"
    published = tmp_path / "datos" / SLUG / ".publicado/timetable"
    baseline = (published / "paradas.yaml").read_text()
    assert bus_data.main(["publish", "--tenant", SLUG], repo_root=tmp_path) == 1
    (working / "paradas.yaml").write_text("invalid: [")
    assert bus_data.main(["publish", "--tenant", SLUG, "--comment", "Bad"], repo_root=tmp_path) == 1
    assert (published / "paradas.yaml").read_text() == baseline
    assert TenantDatasetVersion.objects.using("owner").filter(tenant__slug=SLUG).count() == 1


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
        'if [[ $2 == *" export "* ]]; then cat "$SSH_SOURCE";\n'
        'else cat >"$SSH_CAPTURE"; echo "Imported timetable v2"; fi\n'
    )
    binary.chmod(0o755)
    monkeypatch.setenv("PATH", f"{tmp_path}:{os.environ['PATH']}")
    monkeypatch.setenv("HOST", "fake-host")
    monkeypatch.setenv("SSH_SOURCE", str(source))
    monkeypatch.setenv("SSH_ARGS", str(tmp_path / "args"))
    monkeypatch.setenv("SSH_CAPTURE", str(tmp_path / "captured.tar.gz"))


def test_remote_stream_and_comment_quoting(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_ssh(tmp_path, monkeypatch)
    root = tmp_path / "workspace"
    assert bus_data.main(["download", "--tenant", SLUG, "--prod"], repo_root=root) == 0
    comment = 'Invierno "revisado"; $(do-not-execute)'
    assert (
        bus_data.main(["publish", "--tenant", SLUG, "--comment", comment, "--prod"], repo_root=root)
        == 0
    )
    assert shlex.split((tmp_path / "args").read_text()) == [
        "/srv/autobot/deploy/manage.sh",
        "tenant_dataset",
        "import",
        SLUG,
        "timetable",
        "-",
        "--comment",
        comment,
    ]
    with tarfile.open(tmp_path / "captured.tar.gz", mode="r:gz") as uploaded:
        assert "./paradas.yaml" in uploaded.getnames()


def test_baseline_tracks_uploaded_snapshot_if_working_copy_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_ssh(tmp_path, monkeypatch)
    root = tmp_path / "workspace"
    assert bus_data.main(["download", "--tenant", SLUG, "--prod"], repo_root=root) == 0
    working = root / "datos" / SLUG / "timetable"
    (working / "note.txt").write_text("uploaded")
    real_run = subprocess.run

    def run(*args: Any, **kwargs: Any) -> Any:
        result = real_run(*args, **kwargs)
        (working / "note.txt").write_text("next edit")
        return result

    monkeypatch.setattr(subprocess, "run", run)
    assert (
        bus_data.main(
            ["publish", "--tenant", SLUG, "--comment", "Reviewed", "--prod"], repo_root=root
        )
        == 0
    )
    assert (root / "datos" / SLUG / ".publicado/timetable/note.txt").read_text() == "uploaded"
    assert (working / "note.txt").read_text() == "next edit"
