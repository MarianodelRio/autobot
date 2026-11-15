"""Periodic image prune (A11), exercised locally with a fake `docker`."""

import os
import shutil
import subprocess
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
