"""Periodic image prune (A11), exercised locally with a fake `docker`."""

import os
import shutil
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]


def setup(tmp_path: Path) -> tuple[Path, Path]:
    scripts = tmp_path / "deploy" / "scripts"
    scripts.mkdir(parents=True)
    shutil.copy(ROOT / "deploy/scripts/prune.sh", scripts / "prune.sh")
    binaries = tmp_path / "bin"
    binaries.mkdir()
    docker = binaries / "docker"
    docker.write_text(
        "#!/usr/bin/env bash\n"
        'printf \'%s\\n\' "$*" >>"$TEST_LOG"\n'
        "[[ ${DOCKER_FAIL:-} != 1 ]] || exit 1\n"
    )
    docker.chmod(0o755)
    return scripts / "prune.sh", binaries


def invoke(script: Path, binaries: Path, **environment: str) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "PATH": f"{binaries}:{os.environ['PATH']}",
        "TEST_LOG": str(script.parents[2] / "docker.log"),
    }
    return subprocess.run(
        ["bash", str(script)],
        env={**env, **environment},
        capture_output=True,
        text=True,
        check=False,
    )


def test_prunes_unused_images_older_than_a_day(tmp_path: Path) -> None:
    script, binaries = setup(tmp_path)
    result = invoke(script, binaries)
    assert result.returncode == 0, result.stderr
    log = (tmp_path / "docker.log").read_text()
    assert "image prune" in log
    assert "--all" in log
    assert "until=24h" in log


def test_docker_failure_fails_the_run(tmp_path: Path) -> None:
    script, binaries = setup(tmp_path)
    result = invoke(script, binaries, DOCKER_FAIL="1")
    assert result.returncode != 0


def test_skips_without_failing_while_a_deploy_holds_the_lock(tmp_path: Path) -> None:
    script, binaries = setup(tmp_path)
    (tmp_path / "var").mkdir(exist_ok=True)
    lock_path = tmp_path / "var" / ".deploy.lock"
    holder = subprocess.Popen(["bash", "-c", f'exec 9>"{lock_path}"; flock -x 9; sleep 5'])
    try:
        time.sleep(0.3)  # let the holder actually acquire the lock first
        result = invoke(script, binaries, AUTOBOT_PRUNE_LOCK_WAIT="1")
        assert result.returncode == 0, result.stderr
        assert "deployment is running" in result.stderr
        assert not (tmp_path / "docker.log").exists()
    finally:
        holder.kill()
        holder.wait()


def test_removes_pre_migrate_dump_older_than_two_days(tmp_path: Path) -> None:
    """A8: the dump is a plaintext copy of every client's data, kept outside the
    restic backup on purpose; it must not linger once rolling back to the deploy
    that made it is no longer plausible."""
    script, binaries = setup(tmp_path)
    backups = tmp_path / "var" / "backups"
    backups.mkdir(parents=True)
    old_dump = backups / "pre-migrate.dump"
    old_dump.write_text("DUMPDATA")
    old_time = time.time() - 3 * 24 * 3600
    os.utime(old_dump, (old_time, old_time))
    result = invoke(script, binaries)
    assert result.returncode == 0, result.stderr
    assert not old_dump.exists()


def test_keeps_a_recent_pre_migrate_dump(tmp_path: Path) -> None:
    script, binaries = setup(tmp_path)
    backups = tmp_path / "var" / "backups"
    backups.mkdir(parents=True)
    recent_dump = backups / "pre-migrate.dump"
    recent_dump.write_text("DUMPDATA")
    result = invoke(script, binaries)
    assert result.returncode == 0, result.stderr
    assert recent_dump.exists()


def test_removes_a_stale_temporary_pre_migrate_dump(tmp_path: Path) -> None:
    """A deploy that died mid-dump leaves a plaintext, half-written file behind."""
    script, binaries = setup(tmp_path)
    backups = tmp_path / "var" / "backups"
    backups.mkdir(parents=True)
    stale = backups / "pre-migrate.dump.tmp"
    stale.write_text("HALF")
    result = invoke(script, binaries)
    assert result.returncode == 0, result.stderr
    assert not stale.exists()
