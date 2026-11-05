"""Deployment orchestration, exercised locally with fake Docker and health responses."""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
OLD = "a" * 40
NEW = "b" * 40


def setup(tmp_path: Path, *, previous: bool = True) -> tuple[Path, Path]:
    scripts = tmp_path / "deploy" / "scripts"
    scripts.mkdir(parents=True)
    shutil.copy(ROOT / "deploy/scripts/deploy.sh", scripts / "deploy.sh")
    shutil.copy(ROOT / "deploy/scripts/ensure-env.sh", scripts / "ensure-env.sh")
    (scripts / "ensure-env.sh").chmod(0o755)
    compose = tmp_path / "deploy" / "compose"
    compose.mkdir()
    (compose / "compose.yaml").write_text("services: {}\n")
    (compose / "compose.prod.yaml").write_text("services: {}\n")
    (tmp_path / "var").mkdir()
    if previous:
        (tmp_path / "var" / ".deployed-sha").write_text(OLD + "\n")
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
    return scripts / "deploy.sh", binaries


def deploy_results(tmp_path: Path) -> list[str]:
    path = tmp_path / "var" / "state" / "ops" / "deploys.jsonl"
    return [json.loads(line)["result"] for line in path.read_text().splitlines()]


def invoke(
    script: Path, binaries: Path, *, sha: str = NEW, **environment: str
) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "PATH": f"{binaries}:{os.environ['PATH']}",
        "TEST_LOG": str(script.parents[2] / "docker.log"),
        "PUBLIC_HOST": "api.example.com",
        "DJANGO_ALLOWED_HOSTS": "api.example.com,localhost,127.0.0.1",
        "DEPLOY_UID": "10001",
    }
    return subprocess.run(
        ["bash", str(script), sha],
        env={**env, **environment},
        capture_output=True,
        text=True,
        check=False,
    )


def test_success_records_image_after_health(tmp_path: Path) -> None:
    script, binaries = setup(tmp_path)
    result = invoke(script, binaries)
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "var" / ".deployed-sha").read_text().strip() == NEW
    lines = (tmp_path / "docker.log").read_text().splitlines()
    assert any("migrate" in line for line in lines)
    assert any("tenant_config validate --all" in line for line in lines)
    assert any("seed_demos" in line for line in lines)
    assert any(line.startswith(NEW) and "up --no-deps -d caddy" in line for line in lines)
    assert lines[-1].startswith(NEW) and "deploy_ok" in lines[-1]
    assert deploy_results(tmp_path) == ["deployed"]


def test_already_deployed_and_healthy_is_recorded(tmp_path: Path) -> None:
    script, binaries = setup(tmp_path)
    result = invoke(script, binaries, sha=OLD)
    assert result.returncode == 0, result.stderr
    assert deploy_results(tmp_path) == ["already"]


def test_health_failure_restores_previous_image_and_alerts(tmp_path: Path) -> None:
    script, binaries = setup(tmp_path)
    result = invoke(script, binaries, BROKEN_SHA=NEW)
    assert result.returncode == 1
    assert (tmp_path / "var" / ".deployed-sha").read_text().strip() == OLD
    lines = (tmp_path / "docker.log").read_text().splitlines()
    assert any(line.startswith(OLD) and "up --no-deps -d web worker" in line for line in lines)
    assert any(line.startswith(OLD) and "deploy_rollback" in line for line in lines)
    assert deploy_results(tmp_path) == ["rolled_back"]


def test_worker_restarting_restores_previous_image_and_alerts(tmp_path: Path) -> None:
    script, binaries = setup(tmp_path)
    result = invoke(script, binaries, BROKEN_WORKER_SHA=NEW)
    assert result.returncode == 1
    assert (tmp_path / "var" / ".deployed-sha").read_text().strip() == OLD
    lines = (tmp_path / "docker.log").read_text().splitlines()
    assert any(line.startswith(OLD) and "up --no-deps -d web worker" in line for line in lines)
    assert any(line.startswith(OLD) and "deploy_rollback" in line for line in lines)
    assert not any(line.startswith(NEW) and "-d caddy" in line for line in lines)
    assert deploy_results(tmp_path) == ["rolled_back"]


def test_migration_failure_never_switches_web(tmp_path: Path) -> None:
    script, binaries = setup(tmp_path)
    result = invoke(script, binaries, MIGRATE_FAIL="1")
    assert result.returncode == 1
    assert (tmp_path / "var" / ".deployed-sha").read_text().strip() == OLD
    log = (tmp_path / "docker.log").read_text()
    assert "up --no-deps -d web worker" not in log
    assert any(line.startswith(OLD) and "deploy_aborted" in line for line in log.splitlines())
    assert deploy_results(tmp_path) == ["aborted"]


def test_failure_before_switch_restores_previous_checkout(tmp_path: Path) -> None:
    script, binaries = setup(tmp_path)
    (tmp_path / ".git").mkdir()
    git = binaries / "git"
    git.write_text('#!/usr/bin/env bash\nprintf \'git %s\\n\' "$*" >>"$TEST_LOG"\n')
    git.chmod(0o755)
    result = invoke(script, binaries, PULL_FAIL="1")
    assert result.returncode == 1
    assert (tmp_path / "var" / ".deployed-sha").read_text().strip() == OLD
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
