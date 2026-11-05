"""Tenant transfer uses an actual local export and a fake SSH receiver."""

import os
import subprocess
import tarfile
from pathlib import Path
from urllib.parse import quote

import pytest
import yaml
from django.conf import settings

from tests.helpers.integration import tg_tenant
from tests.platform.tenancy.helpers import TG_SECRETS, seed_db

ROOT = Path(__file__).resolve().parents[4]
pytestmark = pytest.mark.django_db(transaction=True, databases=["default", "owner"])


def environment(tmp_path: Path) -> dict[str, str]:
    binaries = tmp_path / "bin"
    binaries.mkdir()
    ssh = binaries / "ssh"
    ssh.write_text(
        '#!/usr/bin/env bash\nprintf \'%s\\n\' "$@" >"$SSH_ARGUMENTS"\ncat >"$CAPTURE_TAR"\n'
    )
    ssh.chmod(0o755)
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    env = {
        **os.environ,
        "ENVIRONMENT": "local",
        "SENTRY_DSN": "",
        "SLUG": "tg",
        "HOST": "fake-host",
        "SECRETS": "",
        "TMPDIR": str(scratch),
        "CAPTURE_TAR": str(tmp_path / "received.tar.gz"),
        "SSH_ARGUMENTS": str(tmp_path / "ssh.args"),
        "PATH": f"{binaries}:{os.environ['PATH']}",
    }
    for alias, variable in (("owner", "DB_OWNER_URL"), ("default", "DB_APP_URL")):
        db = settings.DATABASES[alias]
        env[variable] = (
            f"postgres://{quote(db['USER'])}:{quote(db['PASSWORD'])}@{db['HOST']}:{db['PORT']}/{quote(db['NAME'])}"
        )
    return env


@pytest.mark.parametrize("include_secrets", [False, True])
def test_push_stream_contains_only_selected_secret(tmp_path: Path, include_secrets: bool) -> None:
    seed_db(tg_tenant(), secrets={"tg": TG_SECRETS}, datasets={"tg": {"rows": {"a.txt": "hello"}}})
    env = environment(tmp_path)
    secret_file = tmp_path / "private.yaml"
    secret_file.write_text(
        yaml.safe_dump({"tg": TG_SECRETS, "other": {"bot_token": "must-not-transfer"}})
    )
    if include_secrets:
        env["SECRETS"] = str(secret_file)
    result = subprocess.run(
        ["bash", "apps/backend/src/tools/tenant_push.sh"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    with tarfile.open(env["CAPTURE_TAR"], mode="r:gz") as archive:
        document = archive.extractfile("./document.yaml")
        assert document is not None and yaml.safe_load(document.read())["slug"] == "tg"
        if include_secrets:
            secret = archive.extractfile("./secrets.yaml")
            assert secret is not None and yaml.safe_load(secret.read()) == {"tg": TG_SECRETS}
            assert archive.getmember("./secrets.yaml").mode == 0o600
        else:
            assert "./secrets.yaml" not in archive.getnames()
        contents = []
        for member in archive:
            if member.isfile():
                stream = archive.extractfile(member)
                assert stream is not None
                contents.append(stream.read())
        assert b"must-not-transfer" not in b"".join(contents)
    assert (tmp_path / "ssh.args").read_text().splitlines() == [
        "deploy@fake-host",
        "/srv/autobot/deploy/manage.sh",
        "tenant_config",
        "import",
        "-",
        "--comment",
        "push",
    ]
    # uv can retain an empty coordinator lock; no exported directory may survive.
    assert all(
        path.is_file()
        and path.name.startswith("uv-")
        and path.suffix == ".lock"
        and path.stat().st_size == 0
        for path in Path(env["TMPDIR"]).iterdir()
    )
    for secret_value in TG_SECRETS.values():
        assert secret_value.encode() not in result.stdout + result.stderr


def test_invalid_slug_never_exports_or_contacts_ssh(tmp_path: Path) -> None:
    env = environment(tmp_path)
    env["SLUG"] = "../escape"
    result = subprocess.run(
        ["bash", "apps/backend/src/tools/tenant_push.sh"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 2
    assert not Path(env["CAPTURE_TAR"]).exists()
    assert not list(Path(env["TMPDIR"]).iterdir())


def test_manage_wrapper_uses_deployed_sha_and_forwards_args(tmp_path: Path) -> None:
    import shutil

    deployment = tmp_path / "deploy"
    deployment.mkdir()
    shutil.copy(ROOT / "deploy/manage.sh", deployment / "manage.sh")
    sha = "a" * 40
    (tmp_path / ".deployed-sha").write_text(sha)
    binary = tmp_path / "docker"
    binary.write_text('#!/usr/bin/env bash\nprintf \'%s\\n\' "$SHA" "$@"\n')
    binary.chmod(0o755)
    result = subprocess.run(
        ["bash", str(deployment / "manage.sh"), "tenant_config", "export", "tg", "-"],
        env={**os.environ, "PATH": f"{tmp_path}:{os.environ['PATH']}"},
        input=b"",
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0
    assert result.stdout.decode().splitlines() == [
        sha,
        "compose",
        "--project-name",
        "autobot",
        "-f",
        "compose.prod.yaml",
        "run",
        "--rm",
        "-T",
        "web",
        "python",
        "manage.py",
        "tenant_config",
        "export",
        "tg",
        "-",
    ]
