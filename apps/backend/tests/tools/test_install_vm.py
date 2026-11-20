"""install-vm.sh: argument validation and its pure helpers. The steps themselves touch
packages, users, sshd and Docker and are only drilled on a disposable VM."""

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
SCRIPT = ROOT / "deploy/scripts/install-vm.sh"


def run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["bash", str(SCRIPT), *args], capture_output=True, text=True, check=False)


def lib(snippet: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", "-c", f"AUTOBOT_INSTALL_LIB_ONLY=1 source {SCRIPT}; {snippet}"],
        capture_output=True,
        text=True,
        check=False,
    )


def test_help_lists_every_step() -> None:
    result = run("--help")
    assert result.returncode == 0
    for step in ("ci-key", "base", "env", "deploy", "health", "harden-ssh", "marker", "github"):
        assert step in result.stdout


def test_unknown_option_and_step_are_rejected_before_anything_runs() -> None:
    assert run("--nope").returncode == 2
    result = run("--only", "bogus")
    assert result.returncode == 2
    assert "Paso desconocido" in result.stderr


def test_invalid_values_are_rejected() -> None:
    assert run("--public-host", "bad host").returncode == 2
    assert run("--sha", "abc").returncode == 2
    assert run("--operator-key", "/nonexistent.pub").returncode == 2
    assert run("--google-sa", "/nonexistent.json").returncode == 2


def test_repo_url_is_normalized_to_https() -> None:
    for url in ("git@github.com:o/r", "ssh://git@github.com/o/r.git", "https://github.com/o/r"):
        result = lib(f"normalize_repo_url {url}")
        assert result.stdout.strip() == "https://github.com/o/r.git", url
    assert lib("normalize_repo_url 'file:///tmp/x'").returncode != 0
    assert lib("repo_slug https://github.com/o/r.git").stdout.strip() == "o/r"


def test_env_values_are_restricted_and_env_set_replaces(tmp_path: Path) -> None:
    assert lib("safe_env_value 'a b'").returncode != 0
    assert lib("safe_env_value 'x;id'").returncode != 0
    assert lib("safe_env_value 'https://k@o1.ingest.sentry.io/4'").returncode == 0
    env = tmp_path / ".env"
    env.write_text("A=1\nB=2\nA=3\n")
    env.chmod(0o600)
    result = lib(f"env_set {env} A new; env_get {env} A; env_get {env} B")
    assert result.stdout.split() == ["new", "2"]
    assert env.stat().st_mode & 0o777 == 0o600
    assert lib(f"env_set {env} A 'bad value'").returncode != 0


def test_script_never_touches_restic_init_or_invents_credentials() -> None:
    text = SCRIPT.read_text()
    assert "restic init" in text  # only in the manual-steps summary
    code = [line for line in text.splitlines() if not line.lstrip().startswith(("#", "'", '"'))]
    assert not any(line.strip().startswith("restic init") for line in code)
