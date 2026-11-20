"""Deployment orchestration, exercised locally with fake Docker and health responses."""

import contextlib
import json
import os
import shutil
import signal
import subprocess
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
OLD = "a" * 40
NEW = "b" * 40
THIRD = "c" * 40


def setup(tmp_path: Path, *, previous: bool = True) -> tuple[Path, Path]:
    scripts = tmp_path / "deploy" / "scripts"
    scripts.mkdir(parents=True)
    shutil.copy(ROOT / "deploy/scripts/deploy.sh", scripts / "deploy.sh")
    shutil.copy(ROOT / "deploy/scripts/ensure-env.sh", scripts / "ensure-env.sh")
    shutil.copy(ROOT / "deploy/scripts/lib.sh", scripts / "lib.sh")
    (scripts / "ensure-env.sh").chmod(0o755)
    compose = tmp_path / "deploy" / "compose"
    compose.mkdir()
    (compose / "compose.yaml").write_text("services: {}\n")
    (compose / "compose.prod.yaml").write_text("services: {}\n")
    caddy = tmp_path / "deploy" / "caddy"
    caddy.mkdir()
    (caddy / "Caddyfile").write_text("example.com {\n}\n")
    (tmp_path / "var").mkdir()
    (tmp_path / "var" / "google_sa.json").write_text("{}\n")
    if previous:
        (tmp_path / "var" / ".deployed-sha").write_text(OLD + "\n")
    binaries = tmp_path / "bin"
    binaries.mkdir()
    docker = binaries / "docker"
    docker.write_text(
        "#!/usr/bin/env bash\n"
        'printf \'%s %s\\n\' "$SHA" "$*" >>"$TEST_LOG"\n'
        "if [[ $* == *'migrate --check'* ]]; then\n"
        "  [[ ${PENDING_MIGRATIONS:-0} == 1 ]] && exit 1 || exit 0\n"
        "fi\n"
        "[[ $* != *migrate* || ${MIGRATE_FAIL:-} != 1 ]] || exit 1\n"
        "[[ $* != *pull* || ${PULL_FAIL:-} != 1 ]] || exit 1\n"
        "if [[ $* == *pg_dump* ]]; then\n"
        "  [[ ${DUMP_FAIL:-} != 1 ]] || exit 1\n"
        "  printf 'DUMPDATA'\n"
        "fi\n"
        "[[ $* != *'caddy reload'* || ${CADDY_RELOAD_FAIL:-} != 1 ]] || exit 1\n"
        "if [[ $* == *'ps -q worker'* ]]; then echo worker-id; fi\n"
        "if [[ $1 == inspect ]]; then\n"
        '  if [[ ${BROKEN_WORKER_SHA:-} == "$SHA" ]]; then echo "true 1"; else echo "true 0"; fi\n'
        "fi\n"
    )
    docker.chmod(0o755)
    curl = binaries / "curl"
    curl.write_text(
        "#!/usr/bin/env bash\n"
        "[[ $* != *https://* || ${BROKEN_HTTPS:-} != 1 ]] || exit 28\n"
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


def deploy_entries(tmp_path: Path) -> list[dict[str, str]]:
    path = tmp_path / "var" / "state" / "ops" / "deploys.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()]


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
        "AUTOBOT_HTTPS_CHECK_TIMEOUT": "2",
        "AUTOBOT_HTTPS_CHECK_INTERVAL": "1",
    }
    return subprocess.run(
        ["bash", str(script), sha],
        env={**env, **environment},
        capture_output=True,
        text=True,
        check=False,
    )


def invoke_env(
    script: Path, binaries: Path, *, sha: str = NEW, **environment: str
) -> dict[str, str]:
    inherited = {k: v for k, v in os.environ.items() if not k.startswith("DB_")}
    return {
        **inherited,
        "PATH": f"{binaries}:{os.environ['PATH']}",
        "TEST_LOG": str(script.parents[2] / "docker.log"),
        "PUBLIC_HOST": "api.example.com",
        "DJANGO_ALLOWED_HOSTS": "api.example.com,localhost,127.0.0.1",
        "DEPLOY_UID": "10001",
        "AUTOBOT_IMAGE": "ghcr.io/example-owner/autobot",
        "AUTOBOT_PANEL_IMAGE": "ghcr.io/example-owner/autobot-panel",
        "AUTOBOT_HTTPS_CHECK_TIMEOUT": "2",
        "AUTOBOT_HTTPS_CHECK_INTERVAL": "1",
        **environment,
    }


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


def test_deploying_back_to_the_previous_sha_is_tagged_as_a_rollback(tmp_path: Path) -> None:
    """A7: deploy.sh marks a deploy that exactly undoes the last one as a rollback,
    so rollback_target.py can refuse to chain a second one onto the broken SHA."""
    script, binaries = setup(tmp_path)
    assert invoke(script, binaries, sha=NEW).returncode == 0
    result = invoke(script, binaries, sha=OLD)
    assert result.returncode == 0, result.stderr
    entries = deploy_entries(tmp_path)
    assert entries[0]["via"] == "deploy"
    assert entries[1]["via"] == "rollback"


def test_an_already_deployed_entry_in_between_does_not_hide_the_rollback(
    tmp_path: Path,
) -> None:
    """A7: deploy.sh must look at the last *successful* ("deployed") entry, not
    simply the last line of deploys.jsonl; an "already" attempt in between (e.g. a
    re-run of `make deploy` for the same SHA) must not make it miss that this
    deploy exactly undoes the last one."""
    script, binaries = setup(tmp_path)
    assert invoke(script, binaries, sha=NEW).returncode == 0
    assert invoke(script, binaries, sha=NEW).returncode == 0
    assert deploy_results(tmp_path) == ["deployed", "already"]
    result = invoke(script, binaries, sha=OLD)
    assert result.returncode == 0, result.stderr
    entries = deploy_entries(tmp_path)
    assert entries[-1]["via"] == "rollback"


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


def test_db_and_caddy_are_pulled_explicitly(tmp_path: Path) -> None:
    """A10: both are pinned by digest (S11) but nothing ever pulled them; `up`
    would otherwise only fetch them lazily, deep inside its own error handling."""
    script, binaries = setup(tmp_path)
    result = invoke(script, binaries)
    assert result.returncode == 0, result.stderr
    log = (tmp_path / "docker.log").read_text()
    assert "pull db caddy" in log


def test_caddy_is_reloaded_when_its_config_changed(tmp_path: Path) -> None:
    """A9: `up` won't recreate Caddy just because a bind-mounted file's content
    changed, so deploy.sh must reload it by hand whenever the Caddyfile did."""
    script, binaries = setup(tmp_path)
    result = invoke(script, binaries)
    assert result.returncode == 0, result.stderr
    log = (tmp_path / "docker.log").read_text()
    assert "exec -T caddy caddy reload" in log
    saved_hash = (tmp_path / "var" / ".caddy-config-sha").read_text()

    # Deploy again, same Caddyfile: nothing changed, no reload needed.
    (tmp_path / "docker.log").unlink()
    result = invoke(script, binaries, sha=THIRD)
    assert result.returncode == 0, result.stderr
    assert "exec -T caddy caddy reload" not in (tmp_path / "docker.log").read_text()
    assert (tmp_path / "var" / ".caddy-config-sha").read_text() == saved_hash


def test_a_failed_caddy_reload_is_retried_on_the_next_deploy(tmp_path: Path) -> None:
    """A9: the Caddyfile hash is only remembered once the reload worked."""
    script, binaries = setup(tmp_path)
    result = invoke(script, binaries, CADDY_RELOAD_FAIL="1")
    assert result.returncode == 0, result.stderr
    assert not (tmp_path / "var" / ".caddy-config-sha").exists()

    (tmp_path / "docker.log").unlink()
    result = invoke(script, binaries, sha=THIRD)
    assert result.returncode == 0, result.stderr
    assert "exec -T caddy caddy reload" in (tmp_path / "docker.log").read_text()
    assert (tmp_path / "var" / ".caddy-config-sha").exists()


def test_https_check_failure_alerts_but_does_not_fail_the_deploy(tmp_path: Path) -> None:
    """A9: DNS/certificate issuance can lag a first deploy; this must only warn."""
    script, binaries = setup(tmp_path)
    result = invoke(script, binaries, BROKEN_HTTPS="1")
    assert result.returncode == 0, result.stderr
    assert deploy_results(tmp_path) == ["deployed"]
    log = (tmp_path / "docker.log").read_text().splitlines()
    assert any("deploy_https_check" in line for line in log)


def test_no_pending_migrations_skips_the_dump(tmp_path: Path) -> None:
    script, binaries = setup(tmp_path)
    result = invoke(script, binaries)
    assert result.returncode == 0, result.stderr
    log = (tmp_path / "docker.log").read_text()
    assert "pg_dump" not in log
    assert not (tmp_path / "var" / "backups" / "pre-migrate.dump").exists()


def test_pending_migrations_are_dumped_before_migrating(tmp_path: Path) -> None:
    """A8: a dump right before a migration that will actually change the schema, so
    a bad one can be restored by hand (neither `abort` nor `rollback` touch it)."""
    script, binaries = setup(tmp_path)
    result = invoke(script, binaries, PENDING_MIGRATIONS="1")
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "var" / "backups" / "pre-migrate.dump").read_text() == "DUMPDATA"
    # It holds every client's data: owner-only, like the other backups.
    assert (tmp_path / "var" / "backups" / "pre-migrate.dump").stat().st_mode & 0o777 == 0o600
    log = (tmp_path / "docker.log").read_text().splitlines()
    dump_index = next(i for i, line in enumerate(log) if "pg_dump" in line)
    migrate_index = next(
        i for i, line in enumerate(log) if "migrate --noinput" in line and "--check" not in line
    )
    assert dump_index < migrate_index


def test_a_failed_dump_aborts_before_migrating(tmp_path: Path) -> None:
    script, binaries = setup(tmp_path)
    result = invoke(script, binaries, PENDING_MIGRATIONS="1", DUMP_FAIL="1")
    assert result.returncode == 1
    log = (tmp_path / "docker.log").read_text()
    assert "migrate --noinput" not in log.replace("migrate --check --noinput", "")
    assert deploy_results(tmp_path) == ["aborted"]
    assert not (tmp_path / "var" / "backups" / "pre-migrate.dump").exists()


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


def test_sighup_does_not_abort_an_in_progress_deploy(tmp_path: Path) -> None:
    """deploy.yml runs this over SSH; a dropped connection must not abandon a
    deploy half-done just because bash's default reaction to SIGHUP is to exit."""
    script, binaries = setup(tmp_path)
    env = invoke_env(script, binaries, sha=NEW)
    process = subprocess.Popen(
        ["bash", str(script), NEW],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    time.sleep(0.2)  # give bash time to reach the `trap '' HUP` line before signalling
    with contextlib.suppress(ProcessLookupError):  # it had already finished; still holds below
        process.send_signal(signal.SIGHUP)
    stdout, stderr = process.communicate(timeout=30)
    assert process.returncode == 0, stderr
    assert deploy_results(tmp_path) == ["deployed"]


def test_refuses_when_frozen(tmp_path: Path) -> None:
    """T4: server-migrate.sh freezes the origin right before its final backup; no
    deploy must touch it while that marker is present."""
    script, binaries = setup(tmp_path)
    (tmp_path / "var" / ".frozen").write_text("")
    result = invoke(script, binaries)
    assert result.returncode == 1
    assert "frozen" in result.stderr
    assert not (tmp_path / "docker.log").exists()


def test_a_failed_caddy_reload_alerts_ops(tmp_path: Path) -> None:
    script, binaries = setup(tmp_path)
    result = invoke(script, binaries, CADDY_RELOAD_FAIL="1")
    assert result.returncode == 0, result.stderr
    log = (tmp_path / "docker.log").read_text().splitlines()
    assert any("deploy_caddy_reload" in line for line in log)


def test_a_lock_held_by_ssh_deploy_is_not_taken_twice(tmp_path: Path) -> None:
    """ssh-deploy.sh locks before its checkout and hands the lock on."""
    import fcntl

    script, binaries = setup(tmp_path)
    lock = open(tmp_path / "var" / ".deploy.lock", "w")  # noqa: SIM115
    fcntl.flock(lock, fcntl.LOCK_EX)
    try:
        blocked = invoke(script, binaries)
        assert blocked.returncode == 1
        assert "Another deployment is running" in blocked.stderr
        handed_on = subprocess.run(
            ["bash", str(script), NEW],
            env=invoke_env(script, binaries, AUTOBOT_DEPLOY_LOCK_HELD="1"),
            capture_output=True,
            text=True,
            check=False,
        )
        assert handed_on.returncode == 0, handed_on.stderr
    finally:
        lock.close()
