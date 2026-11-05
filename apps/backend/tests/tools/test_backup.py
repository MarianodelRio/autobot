"""Backup orchestration, exercised locally with fake Docker and restic."""

import json
import os
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
DUMP_CONTENT = "dump-bytes"


def setup(tmp_path: Path) -> tuple[Path, Path, Path]:
    deploy = tmp_path / "deploy"
    deploy.mkdir()
    shutil.copy(ROOT / "deploy/backup.sh", deploy / "backup.sh")
    (tmp_path / "compose.prod.yaml").write_text("services: {}\n")
    (tmp_path / ".env").write_text("x=1\n")
    (tmp_path / ".deployed-sha").write_text("a" * 40 + "\n")
    (tmp_path / "google_sa.json").write_text("{}\n")
    (deploy / "caddy").mkdir()
    (deploy / "caddy" / "Caddyfile").write_text("x\n")
    config = tmp_path / "backup.env"
    config.write_text(
        "RESTIC_REPOSITORY=local:/tmp/repo\n"
        "RESTIC_PASSWORD_FILE=/tmp/pw\n"
        "HEALTHCHECKS_BACKUP_PING_URL=https://hc.invalid/ping\n"
    )
    binaries = tmp_path / "bin"
    binaries.mkdir()
    docker = binaries / "docker"
    docker.write_text(f"#!/usr/bin/env bash\nprintf '{DUMP_CONTENT}'\n")
    docker.chmod(0o755)
    restic = binaries / "restic"
    restic.write_text(
        "#!/usr/bin/env bash\n"
        'printf \'%s\\n\' "$*" >>"$TEST_LOG"\n'
        "[[ ${RESTIC_FAIL:-} != 1 ]] || exit 1\n"
    )
    restic.chmod(0o755)
    python3 = binaries / "python3"
    python3.write_text("#!/usr/bin/env bash\nexit 0\n")
    python3.chmod(0o755)
    return deploy / "backup.sh", binaries, config


def invoke(
    script: Path, binaries: Path, config: Path, **environment: str
) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "PATH": f"{binaries}:{os.environ['PATH']}",
        "TEST_LOG": str(script.parent.parent / "restic.log"),
        "AUTOBOT_BACKUP_CONFIG": str(config),
    }
    return subprocess.run(
        ["bash", str(script)],
        env={**env, **environment},
        capture_output=True,
        text=True,
        check=False,
    )


def backup_status(tmp_path: Path) -> dict[str, object]:
    status: dict[str, object] = json.loads((tmp_path / "state/ops/backup.json").read_text())
    return status


def test_success_writes_backup_status_and_removes_the_dump(tmp_path: Path) -> None:
    script, binaries, config = setup(tmp_path)
    result = invoke(script, binaries, config)
    assert result.returncode == 0, result.stderr
    status = backup_status(tmp_path)
    assert status["ok"] is True
    assert status["dump_bytes"] == len(DUMP_CONTENT)
    assert not (tmp_path / "backups/autobot.dump").exists()
    log = (tmp_path / "restic.log").read_text()
    assert "backup --tag autobot" in log
    assert "forget --tag autobot" in log


def test_restic_failure_is_recorded_as_not_ok(tmp_path: Path) -> None:
    script, binaries, config = setup(tmp_path)
    result = invoke(script, binaries, config, RESTIC_FAIL="1")
    assert result.returncode != 0
    status = backup_status(tmp_path)
    assert status["ok"] is False
    assert not (tmp_path / "backups/autobot.dump").exists()


def test_missing_config_fails_before_writing_status(tmp_path: Path) -> None:
    script, binaries, config = setup(tmp_path)
    config.unlink()
    result = invoke(script, binaries, config)
    assert result.returncode == 1
    assert not (tmp_path / "state/ops/backup.json").exists()
