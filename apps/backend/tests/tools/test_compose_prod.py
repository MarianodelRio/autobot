"""Hardening of the production compose files: images pinned, no slow-query parameters
in the log, and the two hand-rolled containers (caddy, db) capability-dropped."""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[4]
BASE = yaml.safe_load((ROOT / "deploy/compose/compose.yaml").read_text())
PROD = yaml.safe_load((ROOT / "deploy/compose/compose.prod.yaml").read_text())


def test_db_image_is_pinned_by_digest() -> None:
    assert "@sha256:" in BASE["services"]["db"]["image"]


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
