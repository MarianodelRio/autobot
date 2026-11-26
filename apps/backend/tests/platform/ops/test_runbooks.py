"""Every alert kind raised by the ops checks has a runbook, or says it has none (ADR-018)."""

import ast
import re
from pathlib import Path

from autobot.ops.incidents import KINDS, PREFIXES, kind_info
from autobot.ops.runbooks import (
    NO_RUNBOOK,
    PREFIX_RUNBOOKS,
    RUNBOOKS,
    runbook_path,
    runbook_url,
)

ROOT = Path(__file__).resolve().parents[5]
OPS = ROOT / "apps" / "backend" / "src" / "autobot" / "ops"
DEPLOY = ROOT / "deploy" / "scripts" / "deploy.sh"
KIND = re.compile(r"^[a-z_]+(:|$)")
# `alert_ops <kind> '<text>' [informational]` in deploy.sh.
DEPLOY_ALERT = re.compile(r"^\s*alert_ops (\w+) (['\"]).*?\2( informational)?\s*$", re.M)


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
    """The kinds the sources raise, found by scanning them (never the registry: the guards
    below would then compare the registry with itself)."""
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
    # deploy.sh's; the informational ones (born closed) need no runbook.
    kinds.update(m[0] for m in DEPLOY_ALERT.findall(DEPLOY.read_text()) if not m[2])
    return kinds


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
        "deploy_rollback",
        "outbound_rejected:",
        "failed_job:",
        "container_restarted:",
    } <= kinds
    assert "deploy_ok" not in kinds  # informational


def test_every_raised_kind_is_in_the_registry() -> None:
    """A kind missing from ops/incidents.py would be a condition titled by its key."""
    missing = [
        k
        for k in sorted(source_kinds())
        if k not in KINDS and not any(k.startswith(p) for p in PREFIXES)
    ]
    assert not missing, f"declare them in autobot/ops/incidents.py: {missing}"
    assert kind_info("outbound_rejected:outside_window").nature == "event"
    assert kind_info("failed_job:ops_check").title == "Trabajo fallido: Comprobación de operación"


def test_every_kind_has_a_runbook_or_is_explicitly_without() -> None:
    missing = [k for k in sorted(source_kinds()) if runbook_path(k) is None and k not in NO_RUNBOOK]
    assert not missing, f"add them to autobot/ops/runbooks.py: {missing}"


def test_every_registry_entry_has_a_runbook_or_is_explicitly_without() -> None:
    """Also the kinds no scanned source raises yet (informational ones need none)."""
    declared = {k for k, spec in KINDS.items() if not spec.informational} | set(PREFIXES)
    missing = [k for k in sorted(declared) if runbook_path(k) is None and k not in NO_RUNBOOK]
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


def test_new_kinds_have_their_runbook() -> None:
    assert runbook_url("outbound_rejected:blocked") == (
        "/docs/incidencias/envios-unknown/#envios-rechazados"
    )
    assert (
        runbook_url("failed_job:ops_check") == "/docs/incidencias/cola-y-latido/#trabajos-fallidos"
    )
    assert runbook_url("outbound_ambiguous") == "/docs/incidencias/envios-unknown/"
