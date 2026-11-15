"""`make rollback`'s target picker (A7): refuses to chain a second rollback onto
the broken SHA the first one just moved away from."""

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
SCRIPT = ROOT / "deploy/scripts/rollback_target.py"
GOOD = "a" * 40
BAD = "b" * 40
OLDER = "c" * 40


def run(lines: list[dict[str, object]]) -> subprocess.CompletedProcess[str]:
    stdin = "".join(json.dumps(line) + "\n" for line in lines)
    return subprocess.run(
        [sys.executable, str(SCRIPT)],
        input=stdin,
        capture_output=True,
        text=True,
        check=False,
    )


def test_picks_the_previous_sha_of_the_last_deployment() -> None:
    result = run([{"sha": GOOD, "previous": "", "result": "deployed", "via": "deploy"}])
    assert result.returncode == 1
    result = run(
        [
            {"sha": GOOD, "previous": "", "result": "deployed", "via": "deploy"},
            {"sha": BAD, "previous": GOOD, "result": "deployed", "via": "deploy"},
        ]
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == GOOD


def test_a_second_rollback_in_a_row_is_refused() -> None:
    """A7: without this, it would blindly redeploy BAD, the image just abandoned."""
    result = run(
        [
            {"sha": GOOD, "previous": "", "result": "deployed", "via": "deploy"},
            {"sha": BAD, "previous": GOOD, "result": "deployed", "via": "deploy"},
            # The rollback itself: deploy.sh tagged it "via": "rollback".
            {"sha": GOOD, "previous": BAD, "result": "deployed", "via": "rollback"},
        ]
    )
    assert result.returncode == 1
    assert "rollback" in result.stderr
    assert BAD not in result.stdout


def test_a_fresh_deploy_after_a_rollback_can_roll_back_again() -> None:
    """A later, ordinary deploy clears the "already a rollback" state."""
    result = run(
        [
            {"sha": GOOD, "previous": "", "result": "deployed", "via": "deploy"},
            {"sha": BAD, "previous": GOOD, "result": "deployed", "via": "deploy"},
            {"sha": GOOD, "previous": BAD, "result": "deployed", "via": "rollback"},
            {"sha": OLDER, "previous": GOOD, "result": "deployed", "via": "deploy"},
        ]
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == GOOD


def test_no_deployed_entries_is_refused() -> None:
    result = run([{"sha": GOOD, "previous": "", "result": "aborted", "via": "deploy"}])
    assert result.returncode == 1
    assert "No previous" in result.stderr


def test_ignores_blank_and_malformed_lines() -> None:
    stdin = "\n  \nnot json\n" + json.dumps(
        {"sha": GOOD, "previous": "", "result": "deployed", "via": "deploy"}
    )
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        input=stdin,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    assert "No previous" in result.stderr
