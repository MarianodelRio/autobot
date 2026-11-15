"""restore.sh, exercised locally with fake restic/docker/git (no real containers;
the end-to-end exercise with real Docker and restic is `make restore-test`)."""

import os
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
SHA = "c" * 40


def setup(tmp_path: Path, *, bootstrapped: bool = True) -> tuple[Path, Path]:
    scripts = tmp_path / "deploy" / "scripts"
    scripts.mkdir(parents=True)
    for name in ("restore.sh", "lib.sh", "ensure-env.sh"):
        shutil.copy(ROOT / "deploy/scripts" / name, scripts / name)
        (scripts / name).chmod(0o755)
    compose = tmp_path / "deploy" / "compose"
    compose.mkdir()
    (compose / "compose.yaml").write_text("services: {}\n")
    (compose / "compose.prod.yaml").write_text("services: {}\n")
    (tmp_path / "var").mkdir()
    (tmp_path / "deploy" / "caddy").mkdir()

    # What restic "restores" into the staging directory: a complete, valid snapshot.
    snapshot = tmp_path / "snapshot"
    (snapshot / "var").mkdir(parents=True)
    (snapshot / "var" / "backups").mkdir()
    (snapshot / "deploy" / "caddy").mkdir(parents=True)
    (snapshot / ".env").write_text(
        "PUBLIC_HOST=api.example.com\n"
        "DJANGO_ALLOWED_HOSTS=api.example.com,localhost,127.0.0.1\n"
        "AUTOBOT_IMAGE=ghcr.io/example-owner/autobot\n"
        "AUTOBOT_PANEL_IMAGE=ghcr.io/example-owner/autobot-panel\n"
    )
    (snapshot / "var" / ".deployed-sha").write_text(SHA + "\n")
    (snapshot / "var" / "google_sa.json").write_text("{}\n")
    (snapshot / "deploy" / "caddy" / "Caddyfile").write_text("example.com {\n}\n")
    (snapshot / "var" / "backups" / "autobot.dump").write_text("DUMPDATA\n")

    binaries = tmp_path / "bin"
    binaries.mkdir()
    restic = binaries / "restic"
    restic.write_text(
        "#!/usr/bin/env bash\n"
        'printf \'%s\\n\' "$*" >>"$TEST_LOG"\n'
        "if [[ $1 == restore ]]; then\n"
        '  target="${*: -1}"\n'
        '  cp -r "$RESTIC_FAKE_SNAPSHOT_DIR"/. "$target"/\n'
        "fi\n"
    )
    restic.chmod(0o755)
    docker = binaries / "docker"
    docker.write_text(
        "#!/usr/bin/env bash\n"
        'printf \'%s\\n\' "$*" >>"$TEST_LOG"\n'
        "[[ $* != *'volume inspect'* ]] || exit 1\n"
        "[[ $* != *'ps -q'* ]] || exit 0\n"
    )
    docker.chmod(0o755)
    git = binaries / "git"
    git.write_text('#!/usr/bin/env bash\nprintf \'git %s\\n\' "$*" >>"$TEST_LOG"\n')
    git.chmod(0o755)
    if bootstrapped:
        (tmp_path / "bootstrap-complete").write_text("")
    return scripts / "restore.sh", binaries


def backup_config(tmp_path: Path) -> Path:
    config = tmp_path / "backup.env"
    config.write_text("RESTIC_REPOSITORY=local:/dev/null\nRESTIC_PASSWORD_FILE=/dev/null\n")
    return config


def invoke(
    script: Path, binaries: Path, tmp_path: Path, **environment: str
) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "PATH": f"{binaries}:{os.environ['PATH']}",
        "TEST_LOG": str(tmp_path / "docker.log"),
        "RESTIC_FAKE_SNAPSHOT_DIR": str(tmp_path / "snapshot"),
        "AUTOBOT_BACKUP_CONFIG": str(backup_config(tmp_path)),
        "AUTOBOT_BOOTSTRAP_MARKER": str(tmp_path / "bootstrap-complete"),
    }
    return subprocess.run(
        ["bash", str(script), "--confirm-empty-target"],
        env={**env, **environment},
        capture_output=True,
        text=True,
        check=False,
    )


def test_refuses_without_the_bootstrap_marker(tmp_path: Path) -> None:
    """T1: a target that was never bootstrapped is missing the deploy user, the
    hardening and the systemd timers; restoring onto it must fail loudly."""
    script, binaries = setup(tmp_path, bootstrapped=False)
    result = invoke(script, binaries, tmp_path)
    assert result.returncode == 1
    assert "Bootstrap not done" in result.stderr
    assert not (tmp_path / "docker.log").exists()


def test_workers_are_not_started_by_default(tmp_path: Path) -> None:
    """T1: the real tokens would start sending before DNS/data are verified."""
    script, binaries = setup(tmp_path)
    result = invoke(script, binaries, tmp_path)
    assert result.returncode == 0, result.stderr
    log = (tmp_path / "docker.log").read_text()
    assert "worker-inbound" not in log
    assert "worker-outbound" not in log
    assert "up -d web panel victorialogs caddy" in log


def test_workers_start_when_explicitly_requested(tmp_path: Path) -> None:
    script, binaries = setup(tmp_path)
    result = invoke(script, binaries, tmp_path, AUTOBOT_RESTORE_START_WORKERS="true")
    assert result.returncode == 0, result.stderr
    log = (tmp_path / "docker.log").read_text()
    assert "up -d worker-inbound worker-outbound" in log


def test_checks_out_the_snapshot_sha(tmp_path: Path) -> None:
    """T1: the restored data must match the code that produced it."""
    script, binaries = setup(tmp_path)
    (tmp_path / ".git").mkdir()
    result = invoke(script, binaries, tmp_path)
    assert result.returncode == 0, result.stderr
    log = (tmp_path / "docker.log").read_text()
    assert f"git checkout --quiet --detach {SHA}" in log


def test_restores_optional_caddy_state_and_deploy_log_when_present(tmp_path: Path) -> None:
    """T2: present in the snapshot only if backup.sh had something to back up."""
    script, binaries = setup(tmp_path)
    snapshot = tmp_path / "snapshot"
    (snapshot / "var" / "state" / "caddy-data").mkdir(parents=True)
    (snapshot / "var" / "state" / "caddy-data" / "acme.json").write_text("{}\n")
    (snapshot / "var" / "state" / "ops").mkdir(parents=True)
    (snapshot / "var" / "state" / "ops" / "deploys.jsonl").write_text('{"result":"deployed"}\n')
    result = invoke(script, binaries, tmp_path)
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "var" / "state" / "caddy-data" / "acme.json").read_text() == "{}\n"
    assert (tmp_path / "var" / "state" / "ops" / "deploys.jsonl").read_text() == (
        '{"result":"deployed"}\n'
    )


def test_missing_optional_paths_in_the_snapshot_do_not_fail_the_restore(
    tmp_path: Path,
) -> None:
    script, binaries = setup(tmp_path)
    result = invoke(script, binaries, tmp_path)
    assert result.returncode == 0, result.stderr
    assert not (tmp_path / "var" / "state" / "caddy-data").exists()


def test_db_only_skips_app_services_entirely(tmp_path: Path) -> None:
    script, binaries = setup(tmp_path)
    result = invoke(script, binaries, tmp_path, AUTOBOT_RESTORE_DB_ONLY="true")
    assert result.returncode == 0, result.stderr
    log = (tmp_path / "docker.log").read_text()
    assert "up -d web" not in log
    assert "worker" not in log
