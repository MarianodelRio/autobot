"""Every alert kind raised by the ops checks has a runbook, or says it has none (ADR-018)."""

import ast
import re
from pathlib import Path

from autobot.ops.models import OpsAlert
from autobot.ops.runbooks import (
    NO_RUNBOOK,
    PREFIX_RUNBOOKS,
    RUNBOOKS,
    runbook_path,
    runbook_url,
)
from autobot.panel.routers.incidents import alert_row
from autobot.runtime.notifications import MANUAL_KINDS

ROOT = Path(__file__).resolve().parents[5]
OPS = ROOT / "apps" / "backend" / "src" / "autobot" / "ops"
KIND = re.compile(r"^[a-z_]+(:|$)")


def _kind(node: ast.expr) -> list[str]:
    """The constant text of a kind expression; an f-string gives its constant head
    (`f"calendar:{x}"` -> `calendar:`), which is what the prefix rules match."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, ast.JoinedStr):
        head = node.values[0] if node.values else None
        if isinstance(head, ast.Constant) and isinstance(head.value, str):
            return [head.value]
        return []
    if isinstance(node, ast.IfExp):
        return _kind(node.body) + _kind(node.orelse)
    return []


def _is_text(node: ast.expr) -> bool:
    """A sentence (not a bare word such as the `("deploy", "restore")` of a `in` test)."""
    if isinstance(node, ast.JoinedStr):
        return True
    return isinstance(node, ast.Constant) and isinstance(node.value, str) and " " in node.value


def source_kinds() -> set[str]:
    kinds: set[str] = set()
    for name in ("check.py", "containers.py"):
        tree = ast.parse((OPS / name).read_text())
        for node in ast.walk(tree):
            # Finding("kind", tenant, text)
            if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "Finding":
                kinds.update(_kind(node.args[0]))
            # ("kind", "text") pairs, as appended to `pending` / `findings`
            if isinstance(node, ast.Tuple) and len(node.elts) == 2 and _is_text(node.elts[1]):
                kinds.update(k for k in _kind(node.elts[0]) if KIND.match(k))
    return kinds | set(MANUAL_KINDS)


def test_source_scan_finds_the_known_kinds() -> None:
    # Guards the scan itself: if check.py changes shape and the scan goes blind, fail here.
    kinds = source_kinds()
    assert {
        "inbound_delay",
        "calendar:",
        "container_down:",
        "containers_stale",
        "containers_restore",
        "billing",
        "bot:notify:auth",
        "disk_critical",
        "deploy_aborted",
    } <= kinds


def test_every_kind_has_a_runbook_or_is_explicitly_without() -> None:
    missing = [k for k in sorted(source_kinds()) if runbook_path(k) is None and k not in NO_RUNBOOK]
    assert not missing, f"add them to autobot/ops/runbooks.py: {missing}"


def test_runbook_files_exist() -> None:
    targets = set(RUNBOOKS.values()) | set(PREFIX_RUNBOOKS.values())
    missing = [t for t in sorted(targets) if not (ROOT / "docs" / t.partition("#")[0]).is_file()]
    assert not missing, f"runbook pages that do not exist under docs/: {missing}"


def test_urls_follow_the_site_layout() -> None:
    assert runbook_url("calendar:main") == "/docs/incidencias/calendar/"
    assert runbook_url("container_down:web") == "/docs/incidencias/contenedor-caido/"
    assert runbook_url("containers_restore") == "/docs/procedimientos/restaurar/"
    assert runbook_url("billing") is None
    assert runbook_url("unknown_kind") is None


def test_alert_rows_carry_the_runbook() -> None:
    row = alert_row(OpsAlert(kind="disk", severity="warning", text="x"), {})
    assert row["runbook"] == "/docs/procedimientos/mantenimiento/#disco-lleno"
    assert alert_row(OpsAlert(kind="billing", severity="notice", text="x"), {})["runbook"] is None
