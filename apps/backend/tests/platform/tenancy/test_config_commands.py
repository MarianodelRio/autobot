"""Operator commands round-trip portable config, safe archives and encrypted secrets."""

import io
import os
import subprocess
import sys
import tarfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from urllib.parse import quote

import pytest
import yaml
from django.conf import settings
from django.core.management import call_command
from django.core.management.base import CommandError

from autobot.ops.models import AuditEvent
from autobot.runtime import privacy
from autobot.runtime.models import MetricEvent
from autobot.tenancy import store
from autobot.tenancy.crypto import decrypt
from autobot.tenancy.models import (
    ConfigRevision,
    Tenant,
    TenantDatasetVersion,
    TenantDocumentVersion,
    TenantSecret,
)
from packs.registry import PACKS as REGISTERED
from tests.helpers.integration import tg_tenant
from tests.platform.tenancy.helpers import PACKS, TG_SECRETS

pytestmark = pytest.mark.django_db(transaction=True, databases=["default", "owner"])


@pytest.fixture(autouse=True)
def packs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("packs.registry.PACKS", PACKS | REGISTERED)


def command(name: str, *args: str) -> str:
    output = io.StringIO()
    call_command(name, *args, stdout=output)
    return output.getvalue()


def create() -> dict[str, Any]:
    doc = tg_tenant(owner={"notify": ["greeted"]})
    store.create_tenant(
        document=doc,
        secrets=TG_SECRETS,
        datasets={"rows": {"nested/a.txt": "línea\n"}},
        actor="test",
        comment="Initial",
        keep_status=True,
    )
    return doc


def tar_bytes(files: dict[str, bytes]) -> bytes:
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w:gz") as output:
        for name, content in files.items():
            member = tarfile.TarInfo(name)
            member.size = len(content)
            output.addfile(member, io.BytesIO(content))
    return stream.getvalue()


def test_export_import_directory_and_secrets(tmp_path: Path) -> None:
    create()
    directory = tmp_path / "export"
    command("tenant_config", "export", "tg", str(directory))
    first = TenantDocumentVersion.objects.using("owner").get().document
    assert yaml.safe_load((directory / "document.yaml").read_text()) == first
    assert (directory / "datasets/rows/nested/a.txt").read_text() == "línea\n"
    assert not (directory / "secrets.yaml").exists()
    secrets = tmp_path / "secrets.yaml"
    secrets.write_text(yaml.safe_dump({"tg": {**TG_SECRETS, "bot_token": "new-private"}}))
    assert "v2" in command(
        "tenant_config",
        "import",
        str(directory),
        "--secrets",
        str(secrets),
        "--comment",
        "Roundtrip",
    )
    latest = TenantDocumentVersion.objects.using("owner").latest("version")
    assert latest.document == first
    assert (
        decrypt(bytes(TenantSecret.objects.using("owner").get().ciphertext))["bot_token"]
        == "new-private"
    )
    assert command("tenant_config", "validate", "--all").startswith("Valid: 1")


def test_tar_import_accepts_inline_secret_and_exports_no_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    doc = tg_tenant()
    raw = tar_bytes(
        {
            "document.yaml": yaml.safe_dump(doc).encode(),
            "secrets.yaml": yaml.safe_dump({"tg": TG_SECRETS}).encode(),
        }
    )
    with monkeypatch.context() as patch:
        patch.setattr(sys, "stdin", SimpleNamespace(buffer=io.BytesIO(raw)))
        command("tenant_config", "import", "-")
    assert decrypt(bytes(TenantSecret.objects.using("owner").get().ciphertext)) == TG_SECRETS
    output = io.BytesIO()
    with monkeypatch.context() as patch:
        patch.setattr(sys, "stdout", SimpleNamespace(buffer=output))
        command("tenant_config", "export", "tg", "-")
    with tarfile.open(fileobj=io.BytesIO(output.getvalue()), mode="r:gz") as exported:
        chunks = []
        for member in exported:
            if member.isfile():
                stream = exported.extractfile(member)
                assert stream is not None
                chunks.append(stream.read())
        contents = b"".join(chunks)
        assert not any(name.endswith("secrets.yaml") for name in exported.getnames())
    assert TG_SECRETS["bot_token"].encode() not in contents


def test_dataset_roundtrip_and_no_change(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    create()
    directory = tmp_path / "rows"
    command("tenant_dataset", "export", "tg", "rows", str(directory))
    assert "sin cambios" in command(
        "tenant_dataset", "import", "tg", "rows", str(directory), "--comment", "Same"
    )
    raw = tar_bytes({"nested/a.txt": "otra línea\n".encode()})
    with monkeypatch.context() as patch:
        patch.setattr(sys, "stdin", SimpleNamespace(buffer=io.BytesIO(raw)))
        assert "v2" in command("tenant_dataset", "import", "tg", "rows", "-", "--comment", "Change")
    assert TenantDatasetVersion.objects.using("owner").latest("version").files == {
        "nested/a.txt": "otra línea\n"
    }


def test_import_is_atomic_and_rejects_unsafe_tar(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    create()
    directory = tmp_path / "bad"
    directory.mkdir()
    document = TenantDocumentVersion.objects.using("owner").get().document
    (directory / "document.yaml").write_text(yaml.safe_dump({**document, "name": "Changed"}))
    (directory / "secrets.yaml").write_text(
        yaml.safe_dump({"tg": {"bot_token": "private-incomplete"}})
    )
    with pytest.raises(CommandError) as error:
        command("tenant_config", "import", str(directory))
    assert "private-incomplete" not in str(error.value)
    assert TenantDocumentVersion.objects.using("owner").count() == 1
    assert Tenant.objects.using("owner").get().name == document["name"]
    raw = tar_bytes({"../escape": b"bad"})
    with monkeypatch.context() as patch:
        patch.setattr(sys, "stdin", SimpleNamespace(buffer=io.BytesIO(raw)))
        with pytest.raises(CommandError, match="tar.gz"):
            command("tenant_config", "import", "-")


def test_validation_fails_for_manually_corrupted_document() -> None:
    create()
    TenantDocumentVersion.objects.using("owner").update(document={"bad": True})
    with pytest.raises(CommandError, match="no válidas"):
        command("tenant_config", "validate", "--all")


def test_seed_demos_preserves_operator_changes() -> None:
    assert "created demo-autobuses" in command("seed_demos")
    document = (
        TenantDocumentVersion.objects.using("owner").get(tenant__slug="demo-autobuses").document
    )
    document["name"] = "Modified demo"
    store.publish("demo-autobuses", document=document, base_version=1, actor="user", comment="Keep")
    revision = ConfigRevision.objects.using("owner").get().revision
    assert "exists demo-autobuses" in command("seed_demos")
    assert Tenant.objects.using("owner").get(slug="demo-autobuses").name == "Modified demo"
    assert ConfigRevision.objects.using("owner").get().revision == revision


def test_status_requires_exact_confirmation(monkeypatch: pytest.MonkeyPatch) -> None:
    create()
    command("tenant_status", "tg", "pause")
    assert Tenant.objects.using("owner").get().status == "paused"
    command("tenant_status", "tg", "resume")
    monkeypatch.setattr("builtins.input", lambda prompt: "tg ")
    with pytest.raises(CommandError):
        command("tenant_status", "tg", "offboard")
    monkeypatch.setattr("builtins.input", lambda prompt: "tg")
    command("tenant_status", "tg", "offboard")
    assert Tenant.objects.using("owner").get().status == "offboarded"


def test_purge_requires_offboard_and_leaves_only_sanitized_version() -> None:
    doc = create()
    MetricEvent.objects.using("owner").create(
        tenant_id=doc["id"], kind="event", value=1, idem_key="x"
    )
    tenant = Tenant.objects.using("owner").get()
    with pytest.raises(CommandError, match="offboarded"):
        privacy.purge(tenant)
    store.change_status("tg", action="offboard", confirm_slug="tg", actor="user")
    before = TenantDocumentVersion.objects.using("owner").latest("version").version
    privacy.purge(tenant)
    (latest,) = TenantDocumentVersion.objects.using("owner").all()
    assert latest.version == before + 1
    assert latest.document["testers"] == {"main": []} and latest.document["owner"] is None
    assert not TenantDatasetVersion.objects.using("owner").exists()
    assert not TenantSecret.objects.using("owner").exists()
    assert not MetricEvent.objects.using("owner").exists()
    assert Tenant.objects.using("owner").count() == 1
    assert AuditEvent.objects.using("owner").filter(action="tenant.purge").count() == 1


@pytest.mark.parametrize(
    ("args", "member"),
    [
        (["tenant_config", "export", "demo-autobuses", "-"], "./document.yaml"),
        (["tenant_dataset", "export", "demo-autobuses", "timetable", "-"], "./calendario.yaml"),
    ],
)
def test_cli_binary_export_stdout_is_clean(args: list[str], member: str) -> None:
    command("seed_demos")
    env = {**os.environ, "SENTRY_DSN": "", "ENVIRONMENT": "local"}
    for alias, variable in (("owner", "DB_OWNER_URL"), ("default", "DB_APP_URL")):
        db = settings.DATABASES[alias]
        env[variable] = (
            f"postgres://{quote(db['USER'])}:{quote(db['PASSWORD'])}"
            f"@{db['HOST']}:{db['PORT']}/{quote(db['NAME'])}"
        )
    result = subprocess.run(
        [sys.executable, "manage.py", *args],
        env=env,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    with tarfile.open(fileobj=io.BytesIO(result.stdout), mode="r:gz") as archive:
        document = archive.extractfile(member)
        assert document is not None
        assert yaml.safe_load(document.read())


def test_import_validates_new_document_and_dataset_together(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from dataclasses import replace

    from tests.fixtures.toy_pack.pack import pack

    def load_data(info: Any, config: Any, root: Path) -> object:
        return (root / "datasets" / "rows" / f"{config.greeting}.txt").read_text()

    monkeypatch.setattr("packs.registry.PACKS", {"toy": replace(pack, load_data=load_data)})
    doc = tg_tenant(config={"greeting": "old"})
    store.create_tenant(
        document=doc,
        datasets={"rows": {"old.txt": "old"}},
        actor="test",
        comment="Old",
        keep_status=True,
    )
    directory = tmp_path / "import"
    (directory / "datasets/rows").mkdir(parents=True)
    (directory / "document.yaml").write_text(yaml.safe_dump({**doc, "config": {"greeting": "new"}}))
    (directory / "datasets/rows/new.txt").write_text("new")
    command("tenant_config", "import", str(directory), "--comment", "Both")
    assert (
        TenantDocumentVersion.objects.using("owner")
        .latest("version")
        .document["config"]["greeting"]
        == "new"
    )
    assert TenantDatasetVersion.objects.using("owner").latest("version").files == {"new.txt": "new"}


def test_purge_audit_failure_rolls_back_versions_and_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    create()
    store.change_status("tg", action="offboard", actor="user", confirm_slug="tg")
    revision = ConfigRevision.objects.using("owner").get().revision

    def fail(**kwargs: Any) -> None:
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr(privacy, "record", fail)
    with pytest.raises(RuntimeError):
        privacy.purge(Tenant.objects.using("owner").get())
    assert TenantDocumentVersion.objects.using("owner").count() == 2
    assert TenantSecret.objects.using("owner").count() == 1
    assert TenantDatasetVersion.objects.using("owner").count() == 1
    assert ConfigRevision.objects.using("owner").get().revision == revision
