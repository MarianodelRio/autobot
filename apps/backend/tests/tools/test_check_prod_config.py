"""`tools/ops/check_prod_config.py` (`make check-prod-config`): the pure checks and the
route assertions, run against a simulated proxy in a thread. Nothing here starts Docker
or touches the production Caddy."""

import ast
import json
import shutil
import subprocess
import sys
import threading
from collections.abc import Iterator
from copy import deepcopy
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

import pytest
from cryptography.fernet import Fernet

from tools.ops import check_prod_config as check

_HARDENING = {"cap_drop": ["ALL"], "security_opt": ["no-new-privileges:true"]}


def _good_services() -> dict[str, Any]:
    worker = {
        "read_only": True,
        "environment": {"DB_APP_URL": "x"},
        "networks": {"egress": None, "data": None, "logs": None},
        **_HARDENING,
    }
    return {
        "web": {
            "ports": [{"host_ip": "127.0.0.1"}],
            "volumes": [
                {"target": "/run/secrets/google_sa.json", "read_only": True},
                {"target": "/run/ops", "read_only": True},
            ],
            "read_only": True,
            "user": "10001",
            "environment": {"DB_OWNER_URL": "", "DB_READONLY_URL": ""},
            "networks": {"edge": None, "data": None, "logs": None},
            **_HARDENING,
        },
        "web-panel": {
            "read_only": True,
            "user": "10001",
            "environment": {"DB_OWNER_URL": "postgres://owner", "DB_READONLY_URL": "postgres://ro"},
            "networks": {"panel": None, "data": None, "logs": None},
            **_HARDENING,
        },
        "db": {"environment": {"POSTGRES_PASSWORD": "x"}, "networks": {"data": None}},
        "victorialogs": {"networks": {"logs": None}, **_HARDENING},
        "caddy": {
            "user": "10001",
            "environment": {"PUBLIC_HOST": "x"},
            "networks": {"edge": None},
        },
        "panel": {
            "ports": [{"host_ip": "127.0.0.1"}],
            "read_only": True,
            "user": "10001",
            "networks": {"panel": None},
            **_HARDENING,
        },
        "worker-inbound": deepcopy(worker),
        "worker-outbound": deepcopy(worker),
    }


def test_good_compose_services_pass() -> None:
    check.check_compose_services(_good_services())


@pytest.mark.parametrize(
    "mutate",
    [
        lambda s: s["web"]["ports"][0].update(host_ip="0.0.0.0"),
        lambda s: s["db"].update(ports=[{"published": 5432}]),
        lambda s: s["victorialogs"].update(ports=[{"published": 9428}]),
        lambda s: s["web"]["volumes"][0].update(read_only=False),
        lambda s: s["web"].update(read_only=False),
        lambda s: s["web"].update(user="0"),
        lambda s: s["caddy"].update(user="0"),
        lambda s: s["panel"]["ports"][0].update(host_ip="0.0.0.0"),
        lambda s: s["panel"].update(read_only=False),
        lambda s: s["worker-inbound"]["environment"].update(DB_OWNER_URL="postgres://owner"),
        lambda s: s["worker-outbound"]["environment"].update(FP_OWNER_PASSWORD="x"),
        lambda s: s["worker-outbound"].update(read_only=False),
        lambda s: s["db"]["environment"].update(DJANGO_SECRET_KEY="x"),
        lambda s: s["caddy"]["environment"].update(DB_APP_URL="postgres://app"),
        lambda s: s["web"]["environment"].update(DB_OWNER_URL="postgres://owner"),
        lambda s: s["web"]["environment"].update(DB_READONLY_URL="postgres://ro"),
        lambda s: s["web-panel"]["environment"].update(DB_OWNER_URL=""),
        lambda s: s["web-panel"].update(ports=[{"published": 8000}]),
        lambda s: s["web-panel"]["networks"].update(edge=None),
        lambda s: s["web"]["networks"].update(panel=None),
        lambda s: s["web-panel"].update(cap_drop=[]),
        lambda s: s["victorialogs"].update(security_opt=[]),
        lambda s: s["caddy"]["networks"].update(data=None),
        lambda s: s["db"]["networks"].update(edge=None),
    ],
)
def test_weakened_compose_services_fail(mutate: Any) -> None:
    services = _good_services()
    mutate(services)
    with pytest.raises(AssertionError):
        check.check_compose_services(services)


def test_the_panel_caddyfile_points_at_web_panel_only() -> None:
    check.check_panel_caddyfile()


def test_compose_env_has_a_valid_throwaway_key_and_no_real_secret() -> None:
    env = check.compose_env()
    Fernet(env["SECRETS_ENCRYPTION_KEY"].encode())  # raises if not a valid key
    assert env["DEPLOY_UID"] == "10001"
    assert env["SHA"] == "a" * 40
    assert all("@db/" in env[k] for k in ("DB_APP_URL", "DB_OWNER_URL", "DB_READONLY_URL"))


def test_upstream_server_script_is_valid_python() -> None:
    ast.parse(check.UPSTREAM_SERVER)


def test_run_returns_stdout_and_raises_on_failure() -> None:
    assert check.run(sys.executable, "-c", "print('hola')") == "hola"
    with pytest.raises(RuntimeError):
        check.run(sys.executable, "-c", "import sys; sys.exit(3)")
    assert check.run(sys.executable, "-c", "import sys; sys.exit(3)", check=False) == ""


class _Proxy(BaseHTTPRequestHandler):
    """Behaves like Caddy with the production allowlist, with knobs to break it."""

    leaked: frozenset[str] = frozenset()
    edge = "public"

    def do_GET(self) -> None:
        allowed = self.path in check.PUBLIC_PATHS or self.path in self.leaked
        self.send_response(200 if allowed else 404)
        self.send_header("X-Echo-Edge", self.edge)
        self.end_headers()

    def log_message(self, format: str, *args: Any) -> None:  # silence the test output
        pass


def _serve(**attrs: Any) -> Iterator[int]:
    handler = type("Handler", (_Proxy,), attrs)
    server = HTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_address[1]
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


@pytest.fixture
def good_proxy() -> Iterator[int]:
    yield from _serve()


def test_routes_pass_against_a_correct_proxy(good_proxy: int) -> None:
    check.check_routes(good_proxy)


@pytest.mark.parametrize("path", check.BLOCKED_PATHS)
def test_a_leaked_route_is_detected(path: str) -> None:
    for port in _serve(leaked=frozenset({path})):
        with pytest.raises(AssertionError, match="Public route leaked"):
            check.check_routes(port)


def test_a_public_route_without_the_edge_header_is_detected() -> None:
    for port in _serve(edge=""):
        with pytest.raises(AssertionError):
            check.check_routes(port)


def test_the_allowlist_and_blocklist_do_not_overlap() -> None:
    assert not set(check.PUBLIC_PATHS) & set(check.BLOCKED_PATHS)


def test_root_points_at_the_repository() -> None:
    assert (check.ROOT / "deploy" / "caddy" / "Caddyfile").is_file()
    assert (check.ROOT / "deploy" / "compose" / "compose.prod.yaml").is_file()


@pytest.mark.skipif(shutil.which("docker") is None, reason="needs the docker CLI")
def test_the_repository_production_compose_passes_the_hardening_checks() -> None:
    """Only renders the Compose files (`docker compose config`); starts no container."""
    config = subprocess.run(
        [
            "docker",
            "compose",
            "-f",
            str(check.ROOT / "deploy" / "compose" / "compose.yaml"),
            "-f",
            str(check.ROOT / "deploy" / "compose" / "compose.prod.yaml"),
            "config",
            "--format",
            "json",
        ],
        cwd=check.ROOT,
        env=check.compose_env(),
        capture_output=True,
        text=True,
        check=False,
    )
    if config.returncode:
        pytest.skip(f"docker compose config unavailable: {config.stderr.strip()[:200]}")
    check.check_compose_services(json.loads(config.stdout)["services"])
