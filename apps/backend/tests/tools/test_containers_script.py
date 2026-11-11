"""Host container snapshot script, exercised locally with a fake `docker` and the
real `python3` (the script's own JSON-building step must run unmocked)."""

import fcntl
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[4]
FORBIDDEN_FIELDS = ("Env", "Mounts", "Args", "Cmd", "Health.Log")


def setup(tmp_path: Path) -> tuple[Path, Path]:
    scripts = tmp_path / "deploy" / "scripts"
    scripts.mkdir(parents=True)
    shutil.copy(ROOT / "deploy/scripts/containers.sh", scripts / "containers.sh")
    (tmp_path / "var" / "state" / "ops").mkdir(parents=True)
    binaries = tmp_path / "bin"
    binaries.mkdir()
    docker = binaries / "docker"
    docker.write_text(
        "#!/usr/bin/env bash\n"
        'printf \'%s\\n\' "$*" >>"$TEST_LOG"\n'
        "if [[ $1 == ps ]]; then\n"
        "  [[ ${DOCKER_PS_FAIL:-} != 1 ]] || exit 1\n"
        '  cat "$FAKE_IDS_FILE"\n'
        "elif [[ $1 == inspect ]]; then\n"
        "  [[ ${DOCKER_INSPECT_FAIL:-} != 1 ]] || exit 1\n"
        '  cat "$FAKE_LINES_FILE"\n'
        "fi\n"
    )
    docker.chmod(0o755)
    return scripts / "containers.sh", binaries


def invoke(
    script: Path,
    binaries: Path,
    *,
    ids: str = "",
    lines: str = "",
    **environment: str,
) -> subprocess.CompletedProcess[str]:
    root = script.parents[2]
    ids_file, lines_file = root / "ids.txt", root / "lines.txt"
    ids_file.write_text(ids)
    lines_file.write_text(lines)
    env = {
        **os.environ,
        "PATH": f"{binaries}:{os.environ['PATH']}",
        "TEST_LOG": str(root / "docker.log"),
        "FAKE_IDS_FILE": str(ids_file),
        "FAKE_LINES_FILE": str(lines_file),
    }
    return subprocess.run(
        ["bash", str(script)],
        env={**env, **environment},
        capture_output=True,
        text=True,
        check=False,
    )


def snapshot(root: Path) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(
        (root / "var" / "state" / "ops" / "containers.json").read_text()
    )
    return data


def test_builds_the_expected_document_from_inspect_lines(tmp_path: Path) -> None:
    script, binaries = setup(tmp_path)
    lines = "\n".join(
        [
            json.dumps(
                [
                    "/autobot-web-1",
                    "web",
                    "running",
                    "healthy",
                    0,
                    False,
                    0,
                    "2026-11-11T09:12:40.123456789Z",
                    "0001-01-01T00:00:00Z",
                    "ghcr.io/owner/autobot:abc123",
                ]
            ),
            json.dumps(
                [
                    "/autobot-caddy-1",
                    "caddy",
                    "running",
                    "none",
                    1,
                    True,
                    0,
                    "2026-11-11T09:00:00.000000000Z",
                    "0001-01-01T00:00:00Z",
                    "caddy:2@sha256:" + "a" * 64,
                ]
            ),
        ]
    )
    result = invoke(script, binaries, ids="a\nb", lines=lines)
    assert result.returncode == 0, result.stderr
    doc = snapshot(tmp_path)
    assert doc["version"] == 1
    assert doc["project"] == "autobot"
    assert doc["maintenance"] is None
    assert doc["generated_at"].endswith("Z")
    # Sorted by service then name: caddy before web.
    assert [c["service"] for c in doc["containers"]] == ["caddy", "web"]
    caddy, web = doc["containers"]
    assert caddy["name"] == "autobot-caddy-1"  # leading "/" stripped
    assert caddy["finished_at"] is None  # Docker's zero date becomes null
    assert caddy["oom_killed"] is True
    assert web["started_at"] == "2026-11-11T09:12:40Z"  # nanoseconds dropped


def test_project_without_containers_is_an_empty_list_and_never_calls_inspect(
    tmp_path: Path,
) -> None:
    script, binaries = setup(tmp_path)
    result = invoke(script, binaries, ids="")
    assert result.returncode == 0, result.stderr
    assert snapshot(tmp_path)["containers"] == []
    log = (tmp_path / "docker.log").read_text()
    assert "inspect" not in log


def test_docker_failure_leaves_the_previous_snapshot_untouched(tmp_path: Path) -> None:
    script, binaries = setup(tmp_path)
    previous = tmp_path / "var" / "state" / "ops" / "containers.json"
    previous.write_text('{"version": 1, "old": true}')
    result = invoke(script, binaries, ids="a", DOCKER_INSPECT_FAIL="1")
    assert result.returncode != 0
    assert json.loads(previous.read_text()) == {"version": 1, "old": True}


def test_bad_inspect_output_leaves_no_temp_file_behind(tmp_path: Path) -> None:
    script, binaries = setup(tmp_path)
    previous = tmp_path / "var" / "state" / "ops" / "containers.json"
    previous.write_text('{"version": 1, "old": true}')
    result = invoke(script, binaries, ids="a", lines="not json\n")
    assert result.returncode != 0
    assert json.loads(previous.read_text()) == {"version": 1, "old": True}
    assert list(previous.parent.glob(".containers.json.*")) == []


def test_restore_incomplete_sets_maintenance(tmp_path: Path) -> None:
    script, binaries = setup(tmp_path)
    (tmp_path / "var" / ".restore-incomplete").write_text("")
    result = invoke(script, binaries, ids="")
    assert result.returncode == 0, result.stderr
    assert snapshot(tmp_path)["maintenance"] == "restore"


def test_deploy_lock_held_exclusively_sets_maintenance(tmp_path: Path) -> None:
    script, binaries = setup(tmp_path)
    lock_path = tmp_path / "var" / ".deploy.lock"
    with open(lock_path, "w") as lock_file:
        fcntl.flock(lock_file, fcntl.LOCK_EX)
        result = invoke(script, binaries, ids="")
    assert result.returncode == 0, result.stderr
    assert snapshot(tmp_path)["maintenance"] == "deploy"


def test_no_maintenance_when_neither_applies(tmp_path: Path) -> None:
    script, binaries = setup(tmp_path)
    result = invoke(script, binaries, ids="")
    assert result.returncode == 0, result.stderr
    assert snapshot(tmp_path)["maintenance"] is None


def test_docker_ps_receives_the_project_and_the_oneoff_filter(tmp_path: Path) -> None:
    script, binaries = setup(tmp_path)
    result = invoke(script, binaries, ids="", AUTOBOT_PROJECT="otherproject")
    assert result.returncode == 0, result.stderr
    log = (tmp_path / "docker.log").read_text()
    assert "label=com.docker.compose.project=otherproject" in log
    assert "label=com.docker.compose.oneoff=False" in log


def test_script_never_mentions_the_forbidden_inspect_fields() -> None:
    text = (ROOT / "deploy/scripts/containers.sh").read_text()
    for field in FORBIDDEN_FIELDS:
        assert field not in text
