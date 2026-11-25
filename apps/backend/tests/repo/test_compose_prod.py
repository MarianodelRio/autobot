"""Static guards on deploy/compose/compose.prod.yaml (ADR-020): what production publishes,
which services hold the database owner credentials, and how containers are locked down."""

from pathlib import Path
from typing import Any

import pytest
import yaml

COMPOSE = Path(__file__).resolve().parents[4] / "deploy" / "compose" / "compose.prod.yaml"
BASE = COMPOSE.with_name("compose.yaml")
PUBLIC_EDGE = "caddy"  # the only service allowed to publish on every interface (80/443)
WORKERS = ("worker-inbound", "worker-calendar", "worker-periodic", "worker-outbound")
HARDENED = ("web", "web-panel", *WORKERS, "panel", "victorialogs")


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
    for name in ("db", "victorialogs", "web-panel", *WORKERS):
        assert not services[name].get("ports"), name


def test_only_web_panel_holds_owner_and_readonly_urls(services: dict[str, Any]) -> None:
    for name in ("web", *WORKERS):
        env = services[name]["environment"]
        assert env["DB_OWNER_URL"] == "", name
        assert env["DB_READONLY_URL"] == "", name
    env = services["web-panel"]["environment"]
    assert env["DB_OWNER_URL"] and env["DB_READONLY_URL"]


@pytest.mark.parametrize("name", ("web", "web-panel", *WORKERS))
def test_app_services_get_the_shared_base(services: dict[str, Any], name: str) -> None:
    # The effective environment is compose.yaml's (for the services it defines) merged
    # with compose.prod.yaml's: web-panel, defined only in the latter, once lost the URL
    # and the panel's Logs screen answered "no disponible".
    base = yaml.safe_load(BASE.read_text())["services"].get(name) or {}
    env = {**(base.get("environment") or {}), **(services[name].get("environment") or {})}
    assert env.get("VICTORIALOGS_URL") == "http://victorialogs:9428", name
    depends = {**(base.get("depends_on") or {}), **(services[name].get("depends_on") or {})}
    assert depends.get("db", {}).get("condition") == "service_healthy", name


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
