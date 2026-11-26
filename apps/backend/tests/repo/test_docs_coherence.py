"""Docs <-> code coherence: what the code emits must appear in its reference page.

Every check reads source files only (no database, no Django setup). A failure message says
which page misses what, so the fix is to document it (or to update the extractor here when
the code's shape changed).
"""

import ast
import re
from pathlib import Path

from packs.bus.config import BusConfig
from packs.salon.config import SalonConfig

ROOT = Path(__file__).resolve().parents[4]
SRC = ROOT / "apps" / "backend" / "src"
REF = ROOT / "docs" / "referencia"

ACTION_RE = re.compile(r"^[a-z]+(_[a-z]+)*\.[a-z_]+$")
AUDIT_CALLS = {"record", "record_tenant", "_audit_webhook"}


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _tree(path: Path) -> ast.AST:
    return ast.parse(_read(path), filename=str(path))


def _source_files(*parts: str) -> list[Path]:
    base = SRC.joinpath(*parts)
    return [p for p in base.rglob("*.py") if "migrations" not in p.parts]


def _call_name(node: ast.Call) -> str:
    func = node.func
    if isinstance(func, ast.Attribute):
        return func.attr
    return func.id if isinstance(func, ast.Name) else ""


def _str(node: ast.AST) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _fstring_head(node: ast.AST) -> str | None:
    """The literal text before the first placeholder of an f-string (`f"calendar:{x}"`)."""
    if isinstance(node, ast.JoinedStr) and node.values:
        first = node.values[0]
        return _str(first)
    return None


def _audit_actions() -> dict[str, str]:
    """action -> file where it is recorded: `action=` keywords and the positional actions
    of the audit helpers."""
    found: dict[str, str] = {}
    for path in _source_files("autobot"):
        for node in ast.walk(_tree(path)):
            if not isinstance(node, ast.Call):
                continue
            candidates = [kw.value for kw in node.keywords if kw.arg == "action"]
            if _call_name(node) in AUDIT_CALLS:
                candidates += node.args
            for candidate in candidates:
                value = _str(candidate)
                if value is not None and ACTION_RE.match(value):
                    found.setdefault(value, str(path.relative_to(ROOT)))
    return found


def test_audit_actions_are_extracted() -> None:
    actions = _audit_actions()
    # Guard the extractor itself: if the code's shape changes it must not go silent.
    assert {"tenant.publish", "contact.forget", "data.query", "auth.login"} <= set(actions), (
        f"audit extractor looks broken, found: {sorted(actions)}"
    )


def test_every_audit_action_is_documented() -> None:
    page = _read(REF / "auditoria.md")
    missing = {a: f for a, f in _audit_actions().items() if f"`{a}`" not in page}
    assert not missing, (
        "audit actions recorded in code but missing from docs/referencia/auditoria.md "
        f"(action: file): {missing}"
    )


def test_audit_forbidden_keys_are_documented() -> None:
    from autobot.ops.audit import FORBIDDEN_KEYS

    page = _read(REF / "auditoria.md")
    missing = sorted(key for key in FORBIDDEN_KEYS if f"`{key}`" not in page)
    assert not missing, f"FORBIDDEN_KEYS missing from docs/referencia/auditoria.md: {missing}"


def _alert_keys() -> dict[str, str]:
    """Alert kind (or its literal prefix, for f-strings) -> where the code emits it."""
    found: dict[str, str] = {}

    def add(node: ast.AST, path: Path) -> None:
        key = _str(node)
        if key is None:
            head = _fstring_head(node)
            key = head if head else None
        if key and re.fullmatch(r"[a-z_]+(:[a-z_:]*)?", key):
            found.setdefault(key, str(path.relative_to(ROOT)))

    check = SRC / "autobot" / "ops" / "check.py"
    for node in ast.walk(_tree(check)):
        if not isinstance(node, ast.Call):
            continue
        name = _call_name(node)
        if name == "Finding" and node.args:
            add(node.args[0], check)
        elif name == "append" and node.args and isinstance(node.args[0], ast.Tuple):
            elements = node.args[0].elts
            if len(elements) == 2:  # pending.append((kind, text))
                add(elements[0], check)
    containers = SRC / "autobot" / "ops" / "containers.py"
    for node in ast.walk(_tree(containers)):
        if isinstance(node, ast.Call) and _call_name(node) == "append" and node.args:
            arg = node.args[0]
            if isinstance(arg, ast.Tuple) and len(arg.elts) == 2:
                add(arg.elts[0], containers)
        elif isinstance(node, ast.Tuple) and len(node.elts) == 2:
            head = _str(node.elts[0])
            if head and head.startswith("containers_"):
                add(node.elts[0], containers)
    # The kind registry (ADR-031): every exact key and prefix it declares.
    registry = SRC / "autobot" / "ops" / "incidents.py"
    for node in ast.walk(_tree(registry)):
        if (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id in {"KINDS", "PREFIXES"}
            and isinstance(node.value, ast.Dict)
        ):
            for key in node.value.keys:
                if key is not None:
                    add(key, registry)
    for script in (ROOT / "deploy" / "scripts").glob("*.sh"):
        for match in re.finditer(r"alert_ops\s+(deploy_[a-z_]+)", _read(script)):
            found.setdefault(match.group(1), str(script.relative_to(ROOT)))
    return found


def test_alert_keys_are_extracted() -> None:
    keys = _alert_keys()
    expected = {
        "inbound_delay",
        "failed_job:",
        "outbound_rejected:",
        "outbound_ambiguous",
        "registry",
        "disk",
        "containers_stale",
    }
    assert expected <= set(keys), f"alert extractor looks broken, found: {sorted(keys)}"


def test_every_alert_key_is_documented() -> None:
    page = _read(REF / "alertas.md")
    # A prefix such as `calendar:` (from f"calendar:{channel}") appears as `calendar:<canal>`.
    missing = {k: f for k, f in _alert_keys().items() if f"`{k}" not in page}
    assert not missing, (
        f"alert keys emitted in code but missing from docs/referencia/alertas.md "
        f"(key: file): {missing}"
    )


def test_every_health_issue_code_is_documented() -> None:
    codes: set[str] = set()
    for rel in ("autobot/ops/health.py", "packs/salon/health.py"):
        for node in ast.walk(_tree(SRC / rel)):
            is_issue = isinstance(node, ast.Call) and _call_name(node) in {"Issue", "HealthIssue"}
            if (
                isinstance(node, ast.Call)
                and is_issue
                and node.args
                and (code := _str(node.args[0]))
            ):
                codes.add(code)
    assert {"templates", "degraded", "calendar_unavailable"} <= codes
    page = _read(REF / "alertas.md")
    missing = sorted(code for code in codes if f"`{code}`" not in page and f":{code}`" not in page)
    assert not missing, f"health codes missing from docs/referencia/alertas.md: {missing}"


def test_every_tenant_status_level_is_documented() -> None:
    page = _read(REF / "estados-de-negocio.md")
    levels = ["ok", "notice", "warning", "critical", "unknown"]
    missing = [level for level in levels if f"`{level}`" not in page]
    assert not missing, (
        f"status levels missing from docs/referencia/estados-de-negocio.md: {missing}"
    )


def test_every_salon_config_field_is_documented() -> None:
    page = _read(REF / "packs" / "salon.md")
    fields = set(SalonConfig.model_fields)
    from packs.salon.config import HolidaysConfig, Service, SpecialEvent
    from packs.salon.messages import SalonTexts

    for model in (Service, SpecialEvent, HolidaysConfig, SalonTexts):
        fields |= set(model.model_fields)
    missing = sorted(f for f in fields if f"`{f}`" not in page)
    assert not missing, f"fields missing from docs/referencia/packs/salon.md: {missing}"


def test_every_bus_config_field_is_documented() -> None:
    page = _read(REF / "packs" / "bus.md")
    from packs.bus.config import OfficeHours

    fields = set(BusConfig.model_fields) | set(OfficeHours.model_fields)
    missing = sorted(f for f in fields if f"`{f}`" not in page)
    assert not missing, f"fields missing from docs/referencia/packs/bus.md: {missing}"


def test_every_conversation_step_is_documented() -> None:
    for pack, steps_file in (("salon", "conversation.py"), ("bus", "conversation.py")):
        text = _read(SRC / "packs" / pack / steps_file)
        steps = set(re.findall(r'"((?:BOOK|MOVE|CANCEL)_[A-Z]+|MENU)"', text))
        steps |= set(re.findall(r'^([A-Z_]+) = "\1"$', text, re.MULTILINE))
        page = _read(REF / "packs" / f"{pack}.md")
        missing = sorted(s for s in steps if f"`{s}`" not in page)
        assert not missing, f"states missing from docs/referencia/packs/{pack}.md: {missing}"


def test_deploy_secrets_and_lib_flags_are_documented() -> None:
    page = _read(REF / "variables-entorno.md")
    names = ["DEPLOY_HOST", "DEPLOY_KNOWN_HOSTS", "DEPLOY_SSH_KEY", "AUTOBOT_INSTALL_LIB_ONLY"]
    missing = [n for n in names if f"`{n}`" not in page]
    assert not missing, f"missing from docs/referencia/variables-entorno.md: {missing}"
