"""Deployment orchestration, exercised locally with fake Docker and health responses."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
OLD = "a" * 40
NEW = "b" * 40


def setup(tmp_path: Path, *, previous: bool = True) -> tuple[Path, Path]:
    deploy = tmp_path / "deploy"
    deploy.mkdir()
    shutil.copy(ROOT / "deploy/deploy.sh", deploy / "deploy.sh")
    (tmp_path / "compose.prod.yaml").write_text("services: {}\n")
    if previous:
        (tmp_path / ".deployed-sha").write_text(OLD + "\n")
    binaries = tmp_path / "bin"
    binaries.mkdir()
    docker = binaries / "docker"
    docker.write_text(
        "#!/usr/bin/env bash\n"
        'printf \'%s %s\\n\' "$SHA" "$*" >>"$TEST_LOG"\n'
        "[[ $* != *migrate* || ${MIGRATE_FAIL:-} != 1 ]] || exit 1\n"
        "[[ $* != *pull* || ${PULL_FAIL:-} != 1 ]] || exit 1\n"
        "if [[ $* == *'ps -q worker'* ]]; then echo worker-id; fi\n"
        "if [[ $1 == inspect ]]; then\n"
        '  if [[ ${BROKEN_WORKER_SHA:-} == "$SHA" ]]; then echo "true 1"; else echo "true 0"; fi\n'
        "fi\n"
    )
    docker.chmod(0o755)
    curl = binaries / "curl"
    curl.write_text(
        '#!/usr/bin/env bash\n[[ ${BROKEN_SHA:-} != "$SHA" ]] || exit 22\n'
        'printf \'%s\\n\' \'{"status":"ok","tenants":{"degraded":0,"unreadable":0}}\'\n'
    )
    curl.chmod(0o755)
    sleep = binaries / "sleep"
    sleep.write_text("#!/usr/bin/env bash\nexit 0\n")
    sleep.chmod(0o755)
    return deploy / "deploy.sh", binaries


def invoke(script: Path, binaries: Path, **environment: str) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "PATH": f"{binaries}:{os.environ['PATH']}",
        "TEST_LOG": str(script.parent.parent / "docker.log"),
    }
    return subprocess.run(
        ["bash", str(script), NEW],
        env={**env, **environment},
        capture_output=True,
        text=True,
        check=False,
    )


def test_success_records_image_after_health(tmp_path: Path) -> None:
    script, binaries = setup(tmp_path)
    result = invoke(script, binaries)
    assert result.returncode == 0, result.stderr
    assert (tmp_path / ".deployed-sha").read_text().strip() == NEW
    lines = (tmp_path / "docker.log").read_text().splitlines()
    assert any("migrate" in line for line in lines)
    assert any("sync_tenants" in line for line in lines)
    assert lines[-1].startswith(NEW) and "up --no-deps -d caddy" in lines[-1]


def test_health_failure_restores_previous_image_and_alerts(tmp_path: Path) -> None:
    script, binaries = setup(tmp_path)
    result = invoke(script, binaries, BROKEN_SHA=NEW)
    assert result.returncode == 1
    assert (tmp_path / ".deployed-sha").read_text().strip() == OLD
    lines = (tmp_path / "docker.log").read_text().splitlines()
    assert any(line.startswith(OLD) and "up --no-deps -d web worker" in line for line in lines)
    assert any(line.startswith(OLD) and "deploy_rollback" in line for line in lines)


def test_worker_restarting_restores_previous_image_and_alerts(tmp_path: Path) -> None:
    script, binaries = setup(tmp_path)
    result = invoke(script, binaries, BROKEN_WORKER_SHA=NEW)
    assert result.returncode == 1
    assert (tmp_path / ".deployed-sha").read_text().strip() == OLD
    lines = (tmp_path / "docker.log").read_text().splitlines()
    assert any(line.startswith(OLD) and "up --no-deps -d web worker" in line for line in lines)
    assert any(line.startswith(OLD) and "deploy_rollback" in line for line in lines)
    assert not any(line.startswith(NEW) and "-d caddy" in line for line in lines)


def test_migration_failure_never_switches_web(tmp_path: Path) -> None:
    script, binaries = setup(tmp_path)
    result = invoke(script, binaries, MIGRATE_FAIL="1")
    assert result.returncode == 1
    assert (tmp_path / ".deployed-sha").read_text().strip() == OLD
    log = (tmp_path / "docker.log").read_text()
    assert "up --no-deps -d web worker" not in log
    assert any(line.startswith(OLD) and "deploy_aborted" in line for line in log.splitlines())


def test_failure_before_switch_restores_previous_checkout(tmp_path: Path) -> None:
    script, binaries = setup(tmp_path)
    (tmp_path / ".git").mkdir()
    git = binaries / "git"
    git.write_text('#!/usr/bin/env bash\nprintf \'git %s\\n\' "$*" >>"$TEST_LOG"\n')
    git.chmod(0o755)
    result = invoke(script, binaries, PULL_FAIL="1")
    assert result.returncode == 1
    assert (tmp_path / ".deployed-sha").read_text().strip() == OLD
    log = (tmp_path / "docker.log").read_text()
    assert f"git checkout --quiet --detach {OLD}" in log
    assert "migrate" not in log
    assert "up --no-deps -d web worker" not in log


@pytest.mark.parametrize("argument", ["short", "; rm -rf /", "A" * 40])
def test_rejects_invalid_sha(tmp_path: Path, argument: str) -> None:
    script, binaries = setup(tmp_path)
    result = subprocess.run(
        ["bash", str(script), argument],
        env={**os.environ, "PATH": f"{binaries}:{os.environ['PATH']}"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert not (tmp_path / "docker.log").exists()
