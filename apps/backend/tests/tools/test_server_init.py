"""server-init.sh (A15): only its `--check` step (purely local validation) is
exercised here; the rest touches a real server and is drilled manually in A16."""

import os
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]


def setup(tmp_path: Path) -> tuple[Path, Path]:
    scripts = tmp_path / "deploy" / "scripts"
    scripts.mkdir(parents=True)
    shutil.copy(ROOT / "deploy/scripts/server-init.sh", scripts / "server-init.sh")
    (scripts / "server-init.sh").chmod(0o755)

    operator_key = tmp_path / "operator_ed25519"
    subprocess.run(
        ["ssh-keygen", "-t", "ed25519", "-N", "", "-C", "operator", "-f", str(operator_key)],
        check=True,
        capture_output=True,
    )
    google_sa = tmp_path / "google_sa.json"
    google_sa.write_text("{}\n")

    env_file = tmp_path / "var" / "server.env"
    env_file.parent.mkdir(parents=True)
    env_file.write_text(
        "HOST=198.51.100.10\n"
        "PUBLIC_HOST=api.example.invalid\n"
        "REPO_URL=https://github.com/example-owner/autobot.git\n"
        "AUTOBOT_IMAGE=ghcr.io/example-owner/autobot\n"
        "AUTOBOT_PANEL_IMAGE=ghcr.io/example-owner/autobot-panel\n"
        f"OPERATOR_PUBKEY={operator_key}.pub\n"
        f"GOOGLE_SA_FILE={google_sa}\n"
        "HOST_IP=198.51.100.10\n"
    )

    binaries = tmp_path / "bin"
    binaries.mkdir()
    dig = binaries / "dig"
    dig.write_text(
        "#!/usr/bin/env bash\n"
        "[[ ${DIG_EMPTY:-} != 1 ]] || exit 0\n"
        "printf '%s\\n' \"${DIG_RESULT:-198.51.100.10}\"\n"
    )
    dig.chmod(0o755)
    gh = binaries / "gh"
    gh.write_text("#!/usr/bin/env bash\nexit ${GH_EXIT:-0}\n")
    gh.chmod(0o755)
    return scripts / "server-init.sh", binaries


def invoke(script: Path, binaries: Path, **environment: str) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "PATH": f"{binaries}:{os.environ['PATH']}",
    }
    return subprocess.run(
        ["bash", str(script), "--check"],
        cwd=script.parents[2],
        env={**env, **environment},
        capture_output=True,
        text=True,
        check=False,
    )


def test_check_passes_with_a_complete_server_env(tmp_path: Path) -> None:
    script, binaries = setup(tmp_path)
    result = invoke(script, binaries)
    assert result.returncode == 0, result.stderr
    assert "Local validation OK" in result.stdout


def test_check_fails_on_missing_variable(tmp_path: Path) -> None:
    script, binaries = setup(tmp_path)
    env_file = script.parents[2] / "var" / "server.env"
    lines = [
        line for line in env_file.read_text().splitlines() if not line.startswith("PUBLIC_HOST=")
    ]
    env_file.write_text("\n".join(lines) + "\n")
    result = invoke(script, binaries)
    assert result.returncode == 1
    assert "PUBLIC_HOST" in result.stderr


def test_check_fails_on_an_ssh_url(tmp_path: Path) -> None:
    """The repo is public (ADR-012): REPO_URL must be https://, never an SSH deploy key."""
    script, binaries = setup(tmp_path)
    env_file = script.parents[2] / "var" / "server.env"
    text = env_file.read_text().replace(
        "REPO_URL=https://github.com/example-owner/autobot.git",
        "REPO_URL=git@github.com:example-owner/autobot.git",
    )
    env_file.write_text(text)
    result = invoke(script, binaries)
    assert result.returncode == 1
    assert "https://" in result.stderr


def test_check_fails_when_dns_does_not_resolve(tmp_path: Path) -> None:
    script, binaries = setup(tmp_path)
    result = invoke(script, binaries, DIG_EMPTY="1")
    assert result.returncode == 1
    assert "does not resolve" in result.stderr


def test_check_fails_when_dns_points_elsewhere(tmp_path: Path) -> None:
    script, binaries = setup(tmp_path)
    result = invoke(script, binaries, DIG_RESULT="203.0.113.99")
    assert result.returncode == 1
    assert "resolves to" in result.stderr


def test_check_fails_on_an_invalid_operator_key(tmp_path: Path) -> None:
    script, binaries = setup(tmp_path)
    env_file = script.parents[2] / "var" / "server.env"
    bad_key = script.parents[2] / "bad.pub"
    bad_key.write_text("not a key\n")
    text = "\n".join(
        line if not line.startswith("OPERATOR_PUBKEY=") else f"OPERATOR_PUBKEY={bad_key}"
        for line in env_file.read_text().splitlines()
    )
    env_file.write_text(text)
    result = invoke(script, binaries)
    assert result.returncode == 1
    assert "not a valid public key" in result.stderr


def test_check_touches_nothing_remote(tmp_path: Path) -> None:
    """--check must never call ssh/scp."""
    script, binaries = setup(tmp_path)
    for name in ("ssh", "scp"):
        poison = binaries / name
        poison.write_text("#!/usr/bin/env bash\necho unexpected-network-call >&2\nexit 1\n")
        poison.chmod(0o755)
    result = invoke(script, binaries)
    assert result.returncode == 0, result.stderr
    assert "unexpected-network-call" not in result.stderr
