"""restore.sh, exercised locally with fake restic/docker/git (no real containers;
the end-to-end exercise with real Docker and restic is `make restore-test`)."""

import os
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
SHA = "c" * 40
# A syntactically valid Fernet key (32 bytes, url-safe base64), and another one.
KEY = "ZGVmZ2hpamtsbW5vcHFyc3R1dnd4eXp7fH1-f4CBgoM="
OTHER_KEY = "AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8="
ENV_TEXT = (
    "PUBLIC_HOST=api.example.com\n"
    "DJANGO_ALLOWED_HOSTS=api.example.com,localhost,127.0.0.1\n"
    "AUTOBOT_IMAGE=ghcr.io/example-owner/autobot\n"
    "AUTOBOT_PANEL_IMAGE=ghcr.io/example-owner/autobot-panel\n"
)


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
    # backup.sh stages the .env WITHOUT SECRETS_ENCRYPTION_KEY (ADR-021).
    (snapshot / "var" / "backups" / "autobot.env").write_text(ENV_TEXT)
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
        "[[ $1 != --no-lock ]] || shift\n"
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
        "[[ $* != *'manage.py shell'* || ${DECRYPT_FAIL:-} != 1 ]] || exit 1\n"
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
    # CI exports local DB_*_URL (localhost) for the test suite; ensure-env.sh would
    # rightly reject them as a production .env, so the restore never inherits them.
    inherited = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith("DB_")
        and k not in ("SECRETS_ENCRYPTION_KEY", "AUTOBOT_SECRETS_KEY_FILE")
    }
    key_file = tmp_path / "secrets-key"
    key_file.write_text(KEY + "\n")
    env = {
        **inherited,
        "PATH": f"{binaries}:{os.environ['PATH']}",
        "TEST_LOG": str(tmp_path / "docker.log"),
        "RESTIC_FAKE_SNAPSHOT_DIR": str(tmp_path / "snapshot"),
        "AUTOBOT_BACKUP_CONFIG": str(backup_config(tmp_path)),
        "AUTOBOT_BOOTSTRAP_MARKER": str(tmp_path / "bootstrap-complete"),
        "AUTOBOT_SECRETS_KEY_FILE": str(key_file),
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
    assert "up -d web web-panel panel victorialogs caddy" in log


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


def test_db_only_does_not_mark_the_target_as_deployed(tmp_path: Path) -> None:
    """T4: a DB_ONLY rehearsal (restore-test.sh, or server-migrate.sh's destination
    drill) must not block a later, real restore to the same target."""
    script, binaries = setup(tmp_path)
    result = invoke(script, binaries, tmp_path, AUTOBOT_RESTORE_DB_ONLY="true")
    assert result.returncode == 0, result.stderr
    assert not (tmp_path / "var" / ".deployed-sha").exists()


def test_a_full_restore_marks_the_target_as_deployed(tmp_path: Path) -> None:
    script, binaries = setup(tmp_path)
    result = invoke(script, binaries, tmp_path)
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "var" / ".deployed-sha").read_text().strip() == SHA


def test_refuses_when_frozen(tmp_path: Path) -> None:
    """T4: server-migrate.sh freezes the origin/target it is cutting over; neither
    deploy.sh nor restore.sh must touch it while that marker is present."""
    script, binaries = setup(tmp_path)
    (tmp_path / "var" / ".frozen").write_text("")
    result = invoke(script, binaries, tmp_path)
    assert result.returncode == 1
    assert "frozen" in result.stderr
    assert not (tmp_path / "docker.log").exists()


def test_restores_a_specific_snapshot_when_requested(tmp_path: Path) -> None:
    """T4: the destination must restore the exact snapshot taken at cutover, not
    whatever a concurrent write made "latest"."""
    script, binaries = setup(tmp_path)
    result = invoke(script, binaries, tmp_path, AUTOBOT_RESTORE_SNAPSHOT="abc123")
    assert result.returncode == 0, result.stderr
    log = (tmp_path / "docker.log").read_text()
    assert "restore abc123 --tag autobot" in log


def test_skip_flag_is_explicit_and_loud_instead_of_faking_the_marker(tmp_path: Path) -> None:
    """Drills on a machine that is not a VM (restore-test.sh, localprod.sh) skip the
    bootstrap check out loud; nothing writes the marker for them."""
    script, binaries = setup(tmp_path, bootstrapped=False)
    result = invoke(script, binaries, tmp_path, AUTOBOT_RESTORE_SKIP_BOOTSTRAP_CHECK="true")
    assert result.returncode == 0, result.stderr
    assert "Skipping the bootstrap check" in result.stderr
    assert not (tmp_path / "bootstrap-complete").exists()


def test_the_real_marker_name_is_what_install_vm_writes() -> None:
    install = (ROOT / "deploy/scripts/install-vm.sh").read_text()
    restore = (ROOT / "deploy/scripts/restore.sh").read_text()
    assert "bootstrap_marker=$state_dir/bootstrap-complete" in install
    assert "/var/lib/autobot/bootstrap-complete" in restore
    for name in ("restore-test.sh", "localprod.sh"):
        assert "touch" not in "".join(
            line
            for line in (ROOT / "deploy/scripts" / name).read_text().splitlines()
            if "bootstrap-complete" in line
        )


def _env_lines(tmp_path: Path) -> list[str]:
    return (tmp_path / ".env").read_text().splitlines()


def test_the_key_comes_from_the_given_file_and_lands_in_the_restored_env(tmp_path: Path) -> None:
    """ADR-021: the snapshot has no key; the operator's file is the only source."""
    script, binaries = setup(tmp_path)
    result = invoke(script, binaries, tmp_path)
    assert result.returncode == 0, result.stderr
    assert f"SECRETS_ENCRYPTION_KEY={KEY}" in _env_lines(tmp_path)
    assert KEY not in (tmp_path / "snapshot" / "var" / "backups" / "autobot.env").read_text()


def test_the_key_can_come_from_the_environment_instead_of_a_file(tmp_path: Path) -> None:
    script, binaries = setup(tmp_path)
    result = invoke(
        script, binaries, tmp_path, AUTOBOT_SECRETS_KEY_FILE="", SECRETS_ENCRYPTION_KEY=OTHER_KEY
    )
    assert result.returncode == 0, result.stderr
    assert f"SECRETS_ENCRYPTION_KEY={OTHER_KEY}" in _env_lines(tmp_path)


def test_without_a_key_it_fails_clearly_before_touching_the_target(tmp_path: Path) -> None:
    script, binaries = setup(tmp_path)
    result = invoke(script, binaries, tmp_path, AUTOBOT_SECRETS_KEY_FILE="")
    assert result.returncode == 1
    assert "AUTOBOT_SECRETS_KEY_FILE" in result.stderr
    assert not (tmp_path / ".env").exists()
    assert not (tmp_path / "var" / ".restore-incomplete").exists()
    assert "pg_restore" not in (tmp_path / "docker.log").read_text()


def test_an_unreadable_key_file_fails(tmp_path: Path) -> None:
    script, binaries = setup(tmp_path)
    result = invoke(script, binaries, tmp_path, AUTOBOT_SECRETS_KEY_FILE=str(tmp_path / "nope"))
    assert result.returncode == 1
    assert "not a readable file" in result.stderr


def test_an_invalid_key_is_rejected(tmp_path: Path) -> None:
    script, binaries = setup(tmp_path)
    result = invoke(
        script, binaries, tmp_path, AUTOBOT_SECRETS_KEY_FILE="", SECRETS_ENCRYPTION_KEY="short"
    )
    assert result.returncode == 1
    assert "not a valid Fernet key" in result.stderr
    assert not (tmp_path / ".env").exists()


def test_a_key_that_does_not_decrypt_the_restored_secrets_fails(tmp_path: Path) -> None:
    script, binaries = setup(tmp_path)
    result = invoke(script, binaries, tmp_path, DECRYPT_FAIL="1")
    assert result.returncode == 1
    assert "does not decrypt" in result.stderr
    assert not (tmp_path / "var" / ".deployed-sha").exists()


def test_a_legacy_snapshot_with_the_key_in_its_env_still_restores(tmp_path: Path) -> None:
    """Snapshots taken before ADR-021 carry the whole .env, key included."""
    script, binaries = setup(tmp_path)
    snapshot = tmp_path / "snapshot"
    (snapshot / "var" / "backups" / "autobot.env").unlink()
    (snapshot / ".env").write_text(ENV_TEXT + f"SECRETS_ENCRYPTION_KEY={OTHER_KEY}\n")
    result = invoke(script, binaries, tmp_path, AUTOBOT_SECRETS_KEY_FILE="")
    assert result.returncode == 0, result.stderr
    assert "Legacy snapshot" in result.stderr
    assert f"SECRETS_ENCRYPTION_KEY={OTHER_KEY}" in _env_lines(tmp_path)


def test_the_snapshot_without_any_env_is_refused(tmp_path: Path) -> None:
    script, binaries = setup(tmp_path)
    (tmp_path / "snapshot" / "var" / "backups" / "autobot.env").unlink()
    result = invoke(script, binaries, tmp_path)
    assert result.returncode == 1
    assert "Missing from snapshot" in result.stderr


def test_restic_runs_without_locking(tmp_path: Path) -> None:
    """ADR-021: the credentials on a new server may be upload-only and cannot remove locks."""
    script, binaries = setup(tmp_path)
    result = invoke(script, binaries, tmp_path)
    assert result.returncode == 0, result.stderr
    assert "--no-lock restore" in (tmp_path / "docker.log").read_text()


def test_several_comma_separated_keys_are_accepted(tmp_path: Path) -> None:
    """Mid-rotation SECRETS_ENCRYPTION_KEY is `<new>,<old>` (rotar-secretos.md)."""
    script, binaries = setup(tmp_path)
    result = invoke(
        script,
        binaries,
        tmp_path,
        AUTOBOT_SECRETS_KEY_FILE="",
        SECRETS_ENCRYPTION_KEY=f"{KEY},{OTHER_KEY}",
    )
    assert result.returncode == 0, result.stderr
    assert f"SECRETS_ENCRYPTION_KEY={KEY},{OTHER_KEY}" in _env_lines(tmp_path)
