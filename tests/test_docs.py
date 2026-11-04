"""Every `make` target stays documented (T33's acceptance criterion)."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_every_make_target_is_documented() -> None:
    makefile = (ROOT / "Makefile").read_text()
    targets = {
        target
        for line in makefile.splitlines()
        if line.startswith(".PHONY:")
        for target in line.removeprefix(".PHONY:").split()
    }
    assert targets, "no .PHONY targets found; the Makefile shape may have changed"
    comandos = (ROOT / "docs" / "comandos.md").read_text()
    missing = {target for target in targets if f"make {target}" not in comandos}
    assert not missing, f"undocumented make targets in docs/comandos.md: {sorted(missing)}"


def test_every_manage_command_is_documented() -> None:
    commands = {
        path.stem
        for path in (ROOT / "apps" / "backend" / "autobot" / "management" / "commands").glob("*.py")
        if path.stem != "__init__"
    }
    assert commands, "no management commands found; the layout may have changed"
    comandos = (ROOT / "docs" / "comandos.md").read_text()
    missing = {command for command in commands if not re.search(rf"\b{command}\b", comandos)}
    assert not missing, f"undocumented manage.py commands in docs/comandos.md: {sorted(missing)}"
