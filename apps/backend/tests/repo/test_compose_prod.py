"""Static guards on deploy/compose/compose.prod.yaml (ADR-020): what production publishes,
which services hold the database owner credentials, and how containers are locked down."""

from pathlib import Path
from typing import Any

import pytest
import yaml

COMPOSE = Path(__file__).resolve().parents[4] / "deploy" / "compose" / "compose.prod.yaml"
PUBLIC_EDGE = "caddy"  # the only service allowed to publish on every interface (80/443)
HARDENED = ("web", "web-panel", "worker-inbound", "worker-outbound", "panel", "victorialogs")


@pytest.fixture(scope="module")
def services() -> dict[str, Any]:
    document: dict[str, Any] = yaml.safe_load(COMPOSE.read_text())
    result: dict[str, Any] = document["services"]
    return result


def test_only_caddy_publishes_beyond_loopback(services: dict[str, Any]) -> None:
    for name, service in services.items():
        for port in service.get("ports", []):
            spec = port if isinstance(port, str) else f"{port.get('host_ip', '')}:{port}"
            if name == PUBLIC_EDGE:
                continue
            assert spec.startswith("127.0.0.1:"), f"{name} publishes {spec!r} beyond 127.0.0.1"


def test_caddy_publishes_only_http_and_https(services: dict[str, Any]) -> None:
    targets = {str(port).rsplit(":", 1)[-1] for port in services[PUBLIC_EDGE]["ports"]}
    assert targets == {"80", "443"}


def test_database_and_logs_publish_nothing(services: dict[str, Any]) -> None:
    for name in ("db", "victorialogs", "web-panel", "worker-inbound", "worker-outbound"):
        assert not services[name].get("ports"), name


def test_only_web_panel_holds_owner_and_readonly_urls(services: dict[str, Any]) -> None:
    for name in ("web", "worker-inbound", "worker-outbound"):
        env = services[name]["environment"]
        assert env["DB_OWNER_URL"] == "", name
        assert env["DB_READONLY_URL"] == "", name
    env = services["web-panel"]["environment"]
    assert env["DB_OWNER_URL"] and env["DB_READONLY_URL"]


@pytest.mark.parametrize("name", HARDENED)
def test_containers_drop_capabilities_and_new_privileges(
    services: dict[str, Any], name: str
) -> None:
    service = services[name]
    assert service["cap_drop"] == ["ALL"]
    assert "no-new-privileges:true" in service["security_opt"]
    assert service.get("read_only") is True
    assert all("noexec" in entry and "nosuid" in entry for entry in service["tmpfs"])


def test_caddy_cannot_reach_database_or_logs(services: dict[str, Any]) -> None:
    networks = yaml.safe_load(COMPOSE.read_text())["networks"]
    assert services["caddy"]["networks"] == ["edge"]
    assert not {"data", "logs", "panel"} & set(services["caddy"]["networks"])
    assert networks["data"]["internal"] is True and networks["logs"]["internal"] is True


def test_panel_only_talks_to_web_panel(services: dict[str, Any]) -> None:
    assert services["panel"]["networks"] == ["panel"]
    assert "panel" in services["web-panel"]["networks"]
    assert "panel" not in services["web"]["networks"]
    assert "edge" not in services["web-panel"]["networks"]
