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
        "#!/usr/bin/env bash\n"
        '[[ ${BROKEN_SHA:-} != "$SHA" ]] || exit 22\n'
        # DEGRADED_AFTER while NEW's containers are the last ones started with "up
        # --no-deps [--remove-orphans] -d web worker-inbound worker-outbound panel"
        # (not yet, or restored to a previous sha by a rollback: DEGRADED_BEFORE). Lets
        # a test simulate a tenant already degraded ahead of the deploy, or one that
        # becomes degraded because of it.
        "last=$(grep -E"
        " 'up --no-deps (--remove-orphans )?-d web worker-inbound worker-outbound panel'"
        ' "$TEST_LOG" 2>/dev/null | tail -1)\n'
        f'if [[ $last == "{NEW} "* ]]; then\n'
        "  degraded=${DEGRADED_AFTER:-0}\n"
        "else\n"
        "  degraded=${DEGRADED_BEFORE:-0}\n"
        "fi\n"
        'printf \'{"status":"ok","tenants":{"degraded":%s,"unreadable":0}}\\n\' "$degraded"\n'
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
    # CI exports local DB_*_URL (localhost) for the test suite; ensure-env.sh would
    # rightly reject them as a production .env, so the deploy never inherits them.
    inherited = {k: v for k, v in os.environ.items() if not k.startswith("DB_")}
    env = {
        **inherited,
        "PATH": f"{binaries}:{os.environ['PATH']}",
        "TEST_LOG": str(script.parents[2] / "docker.log"),
        "PUBLIC_HOST": "api.example.com",
        "DJANGO_ALLOWED_HOSTS": "api.example.com,localhost,127.0.0.1",
        "DEPLOY_UID": "10001",
        "AUTOBOT_IMAGE": "ghcr.io/example-owner/autobot",
        "AUTOBOT_PANEL_IMAGE": "ghcr.io/example-owner/autobot-panel",
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
    # The single `worker` from before X14 must not survive the deploy as an orphan.
    assert any(
        line.startswith(NEW)
        and "up --no-deps --remove-orphans -d web worker-inbound worker-outbound panel" in line
        for line in lines
    )
    assert lines[-1].startswith(NEW) and "deploy_ok" in lines[-1]
    assert deploy_results(tmp_path) == ["deployed"]


def test_a_tenant_degraded_before_the_deploy_does_not_block_it(tmp_path: Path) -> None:
    """X10: a tenant already degraded before this deploy (same count before and after)
    must not fail it."""
    script, binaries = setup(tmp_path)
    result = invoke(script, binaries, DEGRADED_BEFORE="1", DEGRADED_AFTER="1")
    assert result.returncode == 0, result.stderr
    assert deploy_results(tmp_path) == ["deployed"]


def test_a_new_degraded_tenant_still_rolls_back(tmp_path: Path) -> None:
    """X10: the deploy still fails when it is the one causing a tenant to degrade."""
    script, binaries = setup(tmp_path)
    result = invoke(script, binaries, DEGRADED_BEFORE="0", DEGRADED_AFTER="1")
    assert result.returncode == 1
    assert deploy_results(tmp_path) == ["rolled_back"]


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
    assert any(line.startswith(OLD) and "-d web worker" in line for line in lines)
    assert any(line.startswith(OLD) and "deploy_rollback" in line for line in lines)
    assert deploy_results(tmp_path) == ["rolled_back"]


def test_worker_restarting_restores_previous_image_and_alerts(tmp_path: Path) -> None:
    script, binaries = setup(tmp_path)
    result = invoke(script, binaries, BROKEN_WORKER_SHA=NEW)
    assert result.returncode == 1
    assert (tmp_path / "var" / ".deployed-sha").read_text().strip() == OLD
    lines = (tmp_path / "docker.log").read_text().splitlines()
    assert any(line.startswith(OLD) and "-d web worker" in line for line in lines)
    assert any(line.startswith(OLD) and "deploy_rollback" in line for line in lines)
    assert not any(line.startswith(NEW) and "-d caddy" in line for line in lines)
    assert deploy_results(tmp_path) == ["rolled_back"]


def test_migration_failure_never_switches_web(tmp_path: Path) -> None:
    script, binaries = setup(tmp_path)
    result = invoke(script, binaries, MIGRATE_FAIL="1")
    assert result.returncode == 1
    assert (tmp_path / "var" / ".deployed-sha").read_text().strip() == OLD
    log = (tmp_path / "docker.log").read_text()
    assert "-d web worker" not in log
    assert any(line.startswith(OLD) and "deploy_aborted" in line for line in log.splitlines())
    assert deploy_results(tmp_path) == ["aborted"]
    # init-roles.sh already ran and gave fp_app its broad grants: the abort must reapply
    # the real ones so they don't linger.
    assert any(
        line.startswith(OLD) and "manage.py apply_grants" in line for line in log.splitlines()
    )


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
    assert "-d web worker" not in log
    assert any(
        line.startswith(OLD) and "manage.py apply_grants" in line for line in log.splitlines()
    )


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
