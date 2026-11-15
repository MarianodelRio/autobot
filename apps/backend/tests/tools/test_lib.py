"""lib.sh, the shared setup sourced by deploy/backup/restore/manage/compose."""

import os
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]


def setup(tmp_path: Path) -> Path:
    scripts = tmp_path / "deploy" / "scripts"
    scripts.mkdir(parents=True)
    shutil.copy(ROOT / "deploy/scripts/lib.sh", scripts / "lib.sh")
    caller = scripts / "caller.sh"
    caller.write_text(
        '#!/usr/bin/env bash\nset -euo pipefail\nsource "$(dirname "$0")/lib.sh"\necho ok\n'
    )
    caller.chmod(0o755)
    return caller


def test_refuses_to_run_as_root(tmp_path: Path) -> None:
    """A6: run as root by mistake, DEPLOY_UID would resolve to 0 downstream."""
    caller = setup(tmp_path)
    binaries = tmp_path / "bin"
    binaries.mkdir()
    fake_id = binaries / "id"
    fake_id.write_text("#!/usr/bin/env bash\necho 0\n")
    fake_id.chmod(0o755)
    result = subprocess.run(
        ["bash", str(caller)],
        env={**os.environ, "PATH": f"{binaries}:{os.environ['PATH']}"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    assert "root" in result.stderr
    assert "ok" not in result.stdout


def test_proceeds_as_a_non_root_user(tmp_path: Path) -> None:
    caller = setup(tmp_path)
    result = subprocess.run(
        ["bash", str(caller)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"
