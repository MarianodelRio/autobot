"""Local import accepts real filesystem paths and optional secrets without SSH."""

import os
import subprocess
from pathlib import Path
from urllib.parse import quote

import pytest
import yaml
from django.conf import settings

from autobot.tenancy.crypto import decrypt
from autobot.tenancy.models import TenantDocumentVersion, TenantSecret
from autobot.tenancy.registry import source_from_dir
from packs.registry import PACKS
from tests.helpers.integration import tg_tenant
from tests.platform.tenancy.helpers import TG_SECRETS

ROOT = Path(__file__).resolve().parents[4]
pytestmark = pytest.mark.django_db(transaction=True, databases=["default", "owner"])


@pytest.mark.parametrize("secrets", [False, True])
def test_make_tenant_import_supports_spaces_and_optional_secrets(
    tmp_path: Path, secrets: bool
) -> None:
    directory = tmp_path / "with spaces"
    directory.mkdir()
    template = PACKS["salon"].template
    assert template is not None
    config = source_from_dir(template).document["config"]
    (directory / "document.yaml").write_text(yaml.safe_dump(tg_tenant(pack="salon", config=config)))
    secret_file = tmp_path / "private input.yaml"
    secret_file.write_text(yaml.safe_dump({"tg": TG_SECRETS}))
    env = {
        **os.environ,
        "ENVIRONMENT": "local",
        "SENTRY_DSN": "",
        "DIR": str(directory),
        "SECRETS": str(secret_file) if secrets else "",
    }
    for alias, variable in (("owner", "DB_OWNER_URL"), ("default", "DB_APP_URL")):
        db = settings.DATABASES[alias]
        env[variable] = (
            f"postgres://{quote(db['USER'])}:{quote(db['PASSWORD'])}@{db['HOST']}:{db['PORT']}/{quote(db['NAME'])}"
        )
    result = subprocess.run(
        ["make", "--no-print-directory", "tenant-import"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert TenantDocumentVersion.objects.using("owner").get().author == "command:tenant_config"
    if secrets:
        assert decrypt(bytes(TenantSecret.objects.using("owner").get().ciphertext)) == TG_SECRETS
    else:
        assert not TenantSecret.objects.using("owner").exists()
    for value in TG_SECRETS.values():
        assert value.encode() not in result.stdout + result.stderr


def test_local_import_requires_directory() -> None:
    result = subprocess.run(
        ["bash", "apps/backend/src/tools/tenant_import.sh"],
        cwd=ROOT,
        env={**os.environ, "DIR": ""},
        capture_output=True,
        check=False,
    )
    assert result.returncode != 0
    assert b"Set DIR" in result.stderr
