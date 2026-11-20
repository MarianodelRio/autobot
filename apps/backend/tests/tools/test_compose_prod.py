"""Hardening of the production compose files: images pinned, no slow-query parameters
in the log, and the two hand-rolled containers (caddy, db) capability-dropped."""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[4]
BASE = yaml.safe_load((ROOT / "deploy/compose/compose.yaml").read_text())
PROD = yaml.safe_load((ROOT / "deploy/compose/compose.prod.yaml").read_text())


def test_db_image_is_pinned_by_digest() -> None:
    assert "@sha256:" in BASE["services"]["db"]["image"]


def test_victorialogs_caps_disk_usage_independently_of_time_retention() -> None:
    """A11: a safety net against the 31d time-based retention filling the disk."""
    command = " ".join(BASE["services"]["victorialogs"]["command"])
    assert "-retentionPeriod=31d" in command
    assert "-retention.maxDiskSpaceUsageBytes=" in command


def test_caddy_image_is_pinned_by_digest() -> None:
    assert "@sha256:" in PROD["services"]["caddy"]["image"]


def test_slow_query_log_never_includes_parameter_values() -> None:
    command = " ".join(PROD["services"]["db"]["command"])
    assert "log_parameter_max_length=0" in command
    assert "log_parameter_max_length_on_error=0" in command


def test_caddy_and_db_drop_capabilities_and_cannot_gain_new_ones() -> None:
    for name in ("caddy", "db"):
        service = PROD["services"][name]
        assert service["cap_drop"] == ["ALL"]
        assert "no-new-privileges:true" in service["security_opt"]


def test_app_services_mount_the_container_snapshot_read_only() -> None:
    for name in ("web", "worker-inbound", "worker-outbound"):
        service = PROD["services"][name]
        assert "../../var/state/ops:/run/ops:ro" in service["volumes"]
        assert service["environment"]["OPS_STATE_DIR"] == "/run/ops"


def test_init_roles_does_not_grant_table_permissions() -> None:
    # Table permissions belong to apply_grants (grants.py); init-roles.sh runs on every
    # deploy and would reopen what grants.py restricts.
    script = (ROOT / "deploy" / "postgres" / "init-roles.sh").read_text()
    code = "\n".join(line for line in script.splitlines() if not line.lstrip().startswith("#"))
    assert "TO fp_app" in code  # CONNECT / schema USAGE only
    assert "ON ALL TABLES" not in code
    assert "ON ALL SEQUENCES" not in code
    assert "GRANT SELECT, INSERT" not in code
