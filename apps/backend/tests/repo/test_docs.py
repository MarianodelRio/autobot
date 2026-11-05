"""Every `make` target stays documented."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]


def test_every_make_target_is_documented() -> None:
    makefile = (ROOT / "Makefile").read_text()
    target_line = re.compile(r"^([a-zA-Z0-9_-]+):.*##")
    targets = {
        match.group(1) for line in makefile.splitlines() if (match := target_line.match(line))
    }
    assert targets, "no documented `target:` lines found; the Makefile shape may have changed"
    comandos = (ROOT / "docs" / "comandos.md").read_text()
    missing = {target for target in targets if f"make {target}" not in comandos}
    assert not missing, f"undocumented make targets in docs/comandos.md: {sorted(missing)}"


def test_every_manage_command_is_documented() -> None:
    commands = {
        path.stem
        for path in (
            ROOT / "apps" / "backend" / "src" / "autobot" / "management" / "commands"
        ).glob("*.py")
        if path.stem != "__init__"
    }
    assert commands, "no management commands found; the layout may have changed"
    comandos = (ROOT / "docs" / "comandos.md").read_text()
    missing = {command for command in commands if not re.search(rf"\b{command}\b", comandos)}
    assert not missing, f"undocumented manage.py commands in docs/comandos.md: {sorted(missing)}"
