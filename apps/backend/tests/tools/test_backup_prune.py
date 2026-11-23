"""backup-prune.sh (ADR-021), exercised with a fake restic: it runs from the operator's
machine with its own credential, never on the server, and only inside the safe window."""

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
SCRIPT = ROOT / "deploy/scripts/backup-prune.sh"


def setup(tmp_path: Path, *, minute: str = "30", mode: int = 0o600) -> tuple[Path, Path]:
    binaries = tmp_path / "bin"
    binaries.mkdir()
    restic = binaries / "restic"
    restic.write_text(
        "#!/usr/bin/env bash\n"
        'printf \'%s|%s|%s\\n\' "$*" "$AWS_ACCESS_KEY_ID" "$RESTIC_REPOSITORY" >>"$TEST_LOG"\n'
    )
    restic.chmod(0o755)
    date = binaries / "date"
    date.write_text(f"#!/usr/bin/env bash\necho {minute}\n")
    date.chmod(0o755)
    config = tmp_path / "prune.env"
    config.write_text(
        "RESTIC_REPOSITORY=local:/tmp/repo\n"
        "RESTIC_PASSWORD_FILE=/tmp/pw\n"
        "AWS_ACCESS_KEY_ID=delete-capable-key\n"
        "AWS_SECRET_ACCESS_KEY=secret\n"
    )
    config.chmod(mode)
    return binaries, config


def invoke(
    tmp_path: Path, binaries: Path, config: Path, *args: str, **environment: str
) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "PATH": f"{binaries}:{os.environ['PATH']}",
        "TEST_LOG": str(tmp_path / "restic.log"),
        "AUTOBOT_PRUNE_CONFIG": str(config),
        "AUTOBOT_BOOTSTRAP_MARKER": str(tmp_path / "no-such-marker"),
        **environment,
    }
    return subprocess.run(
        ["bash", str(SCRIPT), *args], env=env, capture_output=True, text=True, check=False
    )


def test_forgets_and_prunes_with_the_delete_credential(tmp_path: Path) -> None:
    binaries, config = setup(tmp_path)
    result = invoke(tmp_path, binaries, config)
    assert result.returncode == 0, result.stderr
    line = (tmp_path / "restic.log").read_text().splitlines()[0]
    assert line.startswith("forget --tag autobot --group-by tags")
    assert "--keep-daily 7 --keep-weekly 4 --keep-monthly 6 --prune" in line
    assert "delete-capable-key" in line


def test_a_successful_prune_leaves_a_marker_snapshot_the_server_can_read(tmp_path: Path) -> None:
    """ADR-025: the server never deletes, it only reads when the last prune happened."""
    binaries, config = setup(tmp_path)
    result = invoke(tmp_path, binaries, config)
    assert result.returncode == 0, result.stderr
    lines = (tmp_path / "restic.log").read_text().splitlines()
    assert lines[1].startswith("forget --tag autobot-ledger")
    assert lines[2].startswith("backup --stdin --stdin-filename prune-marker --tag autobot-prune")
    assert lines[3].startswith("forget --tag autobot-prune --group-by tags --keep-last 3 --prune")


def test_a_dry_run_leaves_no_marker(tmp_path: Path) -> None:
    binaries, config = setup(tmp_path, minute="00")
    invoke(tmp_path, binaries, config, "--dry-run")
    assert "autobot-prune" not in (tmp_path / "restic.log").read_text()


def test_refuses_to_run_on_the_server(tmp_path: Path) -> None:
    binaries, config = setup(tmp_path)
    marker = tmp_path / "bootstrap-complete"
    marker.write_text("")
    result = invoke(tmp_path, binaries, config, AUTOBOT_BOOTSTRAP_MARKER=str(marker))
    assert result.returncode == 1
    assert "operator machine" in result.stderr
    assert not (tmp_path / "restic.log").exists()


def test_refuses_inside_the_servers_backup_window(tmp_path: Path) -> None:
    binaries, config = setup(tmp_path, minute="03")
    result = invoke(tmp_path, binaries, config)
    assert result.returncode == 1
    assert "backup window" in result.stderr
    assert not (tmp_path / "restic.log").exists()
    allowed = invoke(tmp_path, binaries, config, AUTOBOT_PRUNE_ANYTIME="true")
    assert allowed.returncode == 0, allowed.stderr


def test_dry_run_is_allowed_anytime_and_does_not_prune_for_real(tmp_path: Path) -> None:
    binaries, config = setup(tmp_path, minute="00")
    result = invoke(tmp_path, binaries, config, "--dry-run")
    assert result.returncode == 0, result.stderr
    assert "--dry-run" in (tmp_path / "restic.log").read_text()


def test_the_credential_file_must_be_private(tmp_path: Path) -> None:
    binaries, config = setup(tmp_path, mode=0o644)
    result = invoke(tmp_path, binaries, config)
    assert result.returncode == 1
    assert "0600" in result.stderr


def test_missing_configuration_fails(tmp_path: Path) -> None:
    binaries, config = setup(tmp_path)
    config.unlink()
    result = invoke(tmp_path, binaries, config)
    assert result.returncode == 1
    assert "configuration is missing" in result.stderr


def test_unknown_option_is_a_usage_error(tmp_path: Path) -> None:
    binaries, config = setup(tmp_path)
    assert invoke(tmp_path, binaries, config, "--bogus").returncode == 2
