"""ssh-deploy.sh: the forced command of the CI key. It must take the deploy lock before
it touches the working tree."""

import fcntl
import os
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
GIT = ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid"]


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        [*GIT, *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout.strip()


def setup(tmp_path: Path) -> tuple[Path, str, str]:
    origin = tmp_path / "origin"
    origin.mkdir()
    git(origin, "init", "-q", "-b", "main")
    for name in ("ssh-deploy.sh",):
        (origin / "deploy/scripts").mkdir(parents=True, exist_ok=True)
        shutil.copy(ROOT / "deploy/scripts" / name, origin / "deploy/scripts" / name)
    (origin / "deploy/scripts/deploy.sh").write_text(
        '#!/usr/bin/env bash\necho "deployed $1 lock=$AUTOBOT_DEPLOY_LOCK_HELD" >>"$TEST_LOG"\n'
    )
    (origin / "deploy/compose").mkdir(parents=True)
    (origin / "deploy/compose/compose.prod.yaml").write_text("services: {}\n")
    for path in (origin / "deploy/scripts").iterdir():
        path.chmod(0o755)
    (origin / ".gitignore").write_text("var/\n")
    git(origin, "add", "-A")
    git(origin, "commit", "-qm", "one")
    first = git(origin, "rev-parse", "HEAD")
    (origin / "marker").write_text("two\n")
    git(origin, "add", "-A")
    git(origin, "commit", "-qm", "two")
    second = git(origin, "rev-parse", "HEAD")
    srv = tmp_path / "srv"
    subprocess.run(["git", "clone", "-q", str(origin), str(srv)], check=True)
    git(srv, "checkout", "-q", "--detach", first)
    return srv, first, second


def invoke(srv: Path, tmp_path: Path, command: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(srv / "deploy/scripts/ssh-deploy.sh")],
        env={**os.environ, "SSH_ORIGINAL_COMMAND": command, "TEST_LOG": str(tmp_path / "log")},
        capture_output=True,
        text=True,
        check=False,
    )


def test_checks_out_and_deploys_with_the_lock_handed_on(tmp_path: Path) -> None:
    srv, _first, second = setup(tmp_path)
    result = invoke(srv, tmp_path, f"deploy/scripts/deploy.sh {second}")
    assert result.returncode == 0, result.stderr
    assert git(srv, "rev-parse", "HEAD") == second
    assert (tmp_path / "log").read_text().strip() == f"deployed {second} lock=1"


def test_a_running_deploy_blocks_the_checkout(tmp_path: Path) -> None:
    srv, first, second = setup(tmp_path)
    (srv / "var").mkdir()
    lock = open(srv / "var/.deploy.lock", "w")  # noqa: SIM115
    fcntl.flock(lock, fcntl.LOCK_EX)
    try:
        # Shorten the 10 s wait: the contended case must refuse, not hang the test.
        result = subprocess.run(
            ["bash", "-c", f"cd {srv} && timeout 30 bash deploy/scripts/ssh-deploy.sh"],
            env={**os.environ, "SSH_ORIGINAL_COMMAND": f"deploy/scripts/deploy.sh {second}"},
            capture_output=True,
            text=True,
            check=False,
        )
    finally:
        lock.close()
    assert result.returncode == 1
    assert "Another deployment is running" in result.stderr
    assert git(srv, "rev-parse", "HEAD") == first


def test_anything_but_a_full_sha_deploy_is_refused(tmp_path: Path) -> None:
    srv, _first, _second = setup(tmp_path)
    for command in (
        "bash",
        "deploy/scripts/deploy.sh main",
        "deploy/scripts/deploy.sh " + "a" * 40 + "; id",
    ):
        result = invoke(srv, tmp_path, command)
        assert result.returncode == 2
