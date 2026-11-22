"""Backup orchestration, exercised locally with fake Docker and restic."""

import json
import os
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
DUMP_CONTENT = "dump-bytes"


def setup(tmp_path: Path) -> tuple[Path, Path, Path]:
    scripts = tmp_path / "deploy" / "scripts"
    scripts.mkdir(parents=True)
    shutil.copy(ROOT / "deploy/scripts/backup.sh", scripts / "backup.sh")
    shutil.copy(ROOT / "deploy/scripts/lib.sh", scripts / "lib.sh")
    compose = tmp_path / "deploy" / "compose"
    compose.mkdir()
    (compose / "compose.yaml").write_text("services: {}\n")
    (compose / "compose.prod.yaml").write_text("services: {}\n")
    (tmp_path / ".env").write_text("x=1\nSECRETS_ENCRYPTION_KEY=fixture-key\nY=2\n")
    var = tmp_path / "var"
    var.mkdir()
    (var / ".deployed-sha").write_text("a" * 40 + "\n")
    (var / "google_sa.json").write_text("{}\n")
    (tmp_path / "deploy" / "caddy").mkdir()
    (tmp_path / "deploy" / "caddy" / "Caddyfile").write_text("x\n")
    config = tmp_path / "backup.env"
    config.write_text(
        "RESTIC_REPOSITORY=local:/tmp/repo\n"
        "RESTIC_PASSWORD_FILE=/tmp/pw\n"
        "HEALTHCHECKS_BACKUP_PING_URL=https://hc.invalid/ping\n"
    )
    binaries = tmp_path / "bin"
    binaries.mkdir()
    docker = binaries / "docker"
    docker.write_text(
        "#!/usr/bin/env bash\n"
        "[[ $* != *pg_restore* || ${RESTORE_LIST_FAIL:-} != 1 ]] || exit 1\n"
        f"printf '{DUMP_CONTENT}'\n"
    )
    docker.chmod(0o755)
    restic = binaries / "restic"
    restic.write_text(
        "#!/usr/bin/env bash\n"
        'printf \'%s\\n\' "$*" >>"$TEST_LOG"\n'
        "[[ ${RESTIC_FAIL:-} != 1 ]] || exit 1\n"
        "[[ $1 != cat || ${RESTIC_UNINITIALIZED:-} != 1 ]] || exit 1\n"
        "[[ $1 != check || ${RESTIC_CHECK_FAIL:-} != 1 ]] || exit 1\n"
        "if [[ $1 == backup ]]; then\n"
        '  for arg in "$@"; do\n'
        '    [[ $arg != *.env ]] || cp "$arg" "$TEST_LOG.staged-env"\n'
        "  done\n"
        "fi\n"
        "if [[ $1 == cat ]]; then\n"
        "  id=${RESTIC_REPO_ID:-repo-id-fixture}\n"
        '  printf \'{\\n  "version": 2,\\n  "id": "%s"\\n}\\n\' "$id"\n'
        "fi\n"
    )
    restic.chmod(0o755)
    python3 = binaries / "python3"
    python3.write_text("#!/usr/bin/env bash\nexit 0\n")
    python3.chmod(0o755)
    return scripts / "backup.sh", binaries, config


def invoke(
    script: Path, binaries: Path, config: Path, **environment: str
) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "PATH": f"{binaries}:{os.environ['PATH']}",
        "TEST_LOG": str(script.parents[2] / "restic.log"),
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
    status: dict[str, object] = json.loads(
        (tmp_path / "var" / "state" / "ops" / "backup.json").read_text()
    )
    return status


def test_success_writes_backup_status_and_removes_the_dump(tmp_path: Path) -> None:
    script, binaries, config = setup(tmp_path)
    result = invoke(script, binaries, config)
    assert result.returncode == 0, result.stderr
    status = backup_status(tmp_path)
    assert status["ok"] is True
    assert status["dump_bytes"] == len(DUMP_CONTENT)
    assert not (tmp_path / "var" / "backups" / "autobot.dump").exists()
    log = (tmp_path / "restic.log").read_text()
    assert "backup --tag autobot" in log


def test_optional_caddy_state_and_deploy_log_are_backed_up_when_present(
    tmp_path: Path,
) -> None:
    """T2: Caddy's certificates/account and the deploy log, so losing the server
    doesn't mean reissuing certificates or losing the deploy history."""
    script, binaries, config = setup(tmp_path)
    (tmp_path / "var" / "state" / "caddy-data").mkdir(parents=True)
    (tmp_path / "var" / "state" / "caddy-data" / "acme.json").write_text("{}\n")
    (tmp_path / "var" / "state" / "caddy-config").mkdir()
    (tmp_path / "var" / "state" / "ops").mkdir()
    (tmp_path / "var" / "state" / "ops" / "deploys.jsonl").write_text('{"result":"deployed"}\n')
    result = invoke(script, binaries, config)
    assert result.returncode == 0, result.stderr
    log = (tmp_path / "restic.log").read_text()
    backup_line = next(line for line in log.splitlines() if line.startswith("backup "))
    assert "var/state/caddy-data" in backup_line
    assert "var/state/caddy-config" in backup_line
    assert "var/state/ops/deploys.jsonl" in backup_line


def test_missing_optional_paths_do_not_block_the_backup(tmp_path: Path) -> None:
    script, binaries, config = setup(tmp_path)
    result = invoke(script, binaries, config)
    assert result.returncode == 0, result.stderr
    log = (tmp_path / "restic.log").read_text()
    backup_line = next(line for line in log.splitlines() if line.startswith("backup "))
    assert "caddy-data" not in backup_line
    assert "deploys.jsonl" not in backup_line


def test_uninitialized_repository_fails_without_initializing_it(
    tmp_path: Path,
) -> None:
    """A3: `restic init` is never automatic (a typo in the destination could
    otherwise create a new, empty repository and silently hide the real one)."""
    script, binaries, config = setup(tmp_path)
    result = invoke(script, binaries, config, RESTIC_UNINITIALIZED="1")
    assert result.returncode == 1
    assert "init" in result.stderr
    log = (tmp_path / "restic.log").read_text().splitlines()
    assert log == ["cat config"]
    assert not (tmp_path / "var" / ".restic-repo-id").exists()


def test_first_successful_backup_records_the_repository_id(tmp_path: Path) -> None:
    script, binaries, config = setup(tmp_path)
    result = invoke(script, binaries, config, RESTIC_REPO_ID="repo-a")
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "var" / ".restic-repo-id").read_text() == "repo-a"


def test_a_different_repository_id_refuses_the_backup(tmp_path: Path) -> None:
    """A3: once an id is recorded, a repository that answers with a different one
    (e.g. RESTIC_REPOSITORY was changed to point somewhere else by mistake) must
    not be silently backed up to."""
    script, binaries, config = setup(tmp_path)
    (tmp_path / "var").mkdir(exist_ok=True)
    (tmp_path / "var" / ".restic-repo-id").write_text("repo-a")
    result = invoke(script, binaries, config, RESTIC_REPO_ID="repo-b")
    assert result.returncode == 1
    assert "does not match" in result.stderr
    log = (tmp_path / "restic.log").read_text().splitlines()
    assert log == ["cat config"]


def test_matching_repository_id_proceeds(tmp_path: Path) -> None:
    script, binaries, config = setup(tmp_path)
    (tmp_path / "var").mkdir(exist_ok=True)
    (tmp_path / "var" / ".restic-repo-id").write_text("repo-a")
    result = invoke(script, binaries, config, RESTIC_REPO_ID="repo-a")
    assert result.returncode == 0, result.stderr


def test_restic_failure_is_recorded_as_not_ok(tmp_path: Path) -> None:
    script, binaries, config = setup(tmp_path)
    result = invoke(script, binaries, config, RESTIC_FAIL="1")
    assert result.returncode != 0
    status = backup_status(tmp_path)
    assert status["ok"] is False
    assert not (tmp_path / "var" / "backups" / "autobot.dump").exists()


def test_backup_never_forgets_or_prunes(tmp_path: Path) -> None:
    """ADR-021: the server's credential has no delete permission; expiring snapshots is
    deploy/scripts/backup-prune.sh, from the operator's machine."""
    script, binaries, config = setup(tmp_path)
    result = invoke(script, binaries, config)
    assert result.returncode == 0, result.stderr
    log = (tmp_path / "restic.log").read_text()
    assert "forget" not in log and "prune" not in log
    assert not (tmp_path / "var" / ".last-prune").exists()


def test_the_encryption_key_never_travels_in_the_snapshot(tmp_path: Path) -> None:
    """ADR-021: the staged .env lacks SECRETS_ENCRYPTION_KEY; nothing else is lost."""
    script, binaries, config = setup(tmp_path)
    result = invoke(script, binaries, config)
    assert result.returncode == 0, result.stderr
    log = (tmp_path / "restic.log").read_text()
    backup_line = next(line for line in log.splitlines() if line.startswith("backup "))
    assert "var/backups/autobot.env" in backup_line
    assert " .env" not in backup_line
    staged = (tmp_path / "restic.log.staged-env").read_text()
    assert "SECRETS_ENCRYPTION_KEY" not in staged and "fixture-key" not in staged
    assert "x=1" in staged and "Y=2" in staged
    assert not (tmp_path / "var" / "backups" / "autobot.env").exists()


def test_missing_config_fails_before_writing_status(tmp_path: Path) -> None:
    script, binaries, config = setup(tmp_path)
    config.unlink()
    result = invoke(script, binaries, config)
    assert result.returncode == 1
    assert not (tmp_path / "var" / "state" / "ops" / "backup.json").exists()


def test_a_corrupt_dump_is_never_uploaded(tmp_path: Path) -> None:
    script, binaries, config = setup(tmp_path)
    result = invoke(script, binaries, config, RESTORE_LIST_FAIL="1")
    assert result.returncode == 1
    assert "pg_restore --list" in result.stderr
    log = (tmp_path / "restic.log").read_text()
    assert "backup --tag" not in log
    assert backup_status(tmp_path)["ok"] is False


def test_not_enough_free_space_fails_before_dumping(tmp_path: Path) -> None:
    script, binaries, config = setup(tmp_path)
    result = invoke(script, binaries, config, AUTOBOT_BACKUP_MIN_FREE_BYTES=str(10**18))
    assert result.returncode == 1
    assert "Not enough free disk space" in result.stderr
    assert "backup --tag" not in (tmp_path / "restic.log").read_text()


def test_restic_check_runs_once_a_week_and_failure_fails_the_backup(tmp_path: Path) -> None:
    script, binaries, config = setup(tmp_path)
    first = invoke(script, binaries, config)
    assert first.returncode == 0, first.stderr
    log = (tmp_path / "restic.log").read_text().splitlines()
    assert any(line.startswith("check --read-data-subset=") for line in log)
    (tmp_path / "restic.log").unlink()
    second = invoke(script, binaries, config)
    assert second.returncode == 0, second.stderr
    assert not any(" check " in line for line in (tmp_path / "restic.log").read_text().splitlines())
    (tmp_path / "var" / ".last-restic-check").unlink()
    failing = invoke(script, binaries, config, RESTIC_CHECK_FAIL="1")
    assert failing.returncode != 0
    assert not (tmp_path / "var" / ".last-restic-check").exists()
