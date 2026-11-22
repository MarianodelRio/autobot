"""Exercise Caddy's production allowlist against a local dummy upstream."""

import json
import os
import shutil
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet

# `make check-prod-config` runs this file as a plain script (src/ is not on sys.path), so
# it cannot import `tools._paths`: src/tools/ops/<this file> -> repository root.
ROOT = Path(__file__).resolve().parents[5]
NAME = f"fp-config-{uuid.uuid4().hex[:12]}"
BACKEND = f"{NAME}-backend"
PROXY = f"{NAME}-caddy"


def run(*args: str, check: bool = True) -> str:
    result = subprocess.run(args, capture_output=True, text=True, check=False)
    if check and result.returncode:
        raise RuntimeError(f"{' '.join(args[:3])}: {result.stderr.strip()}")
    return result.stdout.strip()


# Every upstream path returns 200: a 404 can only come from Caddy. Echoes
# X-Autobot-Edge back so the check can see Caddy actually set it.
UPSTREAM_SERVER = (
    "from http.server import BaseHTTPRequestHandler,HTTPServer; "
    "H=type('H',(BaseHTTPRequestHandler,),{'do_GET':lambda s:"
    "(s.send_response(200),"
    "s.send_header('X-Echo-Edge', s.headers.get('X-Autobot-Edge','')),"
    "s.end_headers())}); "
    "HTTPServer(('0.0.0.0',8000),H).serve_forever()"
)

# Routes Caddy must forward to the app, and routes it must answer with 404 itself.
PUBLIC_PATHS = (
    "/health",
    "/webhooks/telegram-demo",
    "/webhooks/whatsapp-demo",
    "/webhooks/telegram/abc",
    "/webhooks/whatsapp/abc",
)
BLOCKED_PATHS = (
    "/",
    "/admin/",
    "/static/admin/css/base.css",
    "/health/",
    "/webhooks/telegram",
    "/webhooks/telegram-test",
)


def compose_env() -> dict[str, str]:
    """Throwaway environment for `docker compose config` (placeholders, no real secret)."""
    return {
        **os.environ,
        "SECRETS_ENCRYPTION_KEY": Fernet.generate_key().decode(),
        "SHA": "a" * 40,
        "AUTOBOT_IMAGE": "ghcr.io/example-owner/autobot",
        "AUTOBOT_PANEL_IMAGE": "ghcr.io/example-owner/autobot-panel",
        "PUBLIC_HOST": "localhost",
        "DJANGO_SECRET_KEY": "local-config-check-only",
        "DJANGO_ALLOWED_HOSTS": "localhost",
        "DB_APP_URL": "postgres://fp_app:local@db/autobot",
        "DB_OWNER_URL": "postgres://fp_owner:local@db/autobot",
        "DB_READONLY_URL": "postgres://fp_readonly:local@db/autobot",
        "POSTGRES_PASSWORD": "local",
        "FP_OWNER_PASSWORD": "local",
        "FP_APP_PASSWORD": "local",
        "FP_READONLY_PASSWORD": "local",
        "DEPLOY_UID": "10001",
    }


def check_compose_services(services: dict[str, Any]) -> None:
    """Assert the production hardening of the rendered Compose services."""
    assert services["web"]["ports"][0]["host_ip"] == "127.0.0.1"
    # ADR-020: the public web holds fp_app alone; the panel's API (web-panel) is the only
    # long-running service with fp_owner/fp_readonly, and it publishes no port at all.
    assert not services["web"]["environment"].get("DB_OWNER_URL")
    assert not services["web"]["environment"].get("DB_READONLY_URL")
    assert services["web-panel"]["environment"].get("DB_OWNER_URL")
    assert services["web-panel"]["environment"].get("DB_READONLY_URL")
    assert not services["web-panel"].get("ports")
    assert services["web-panel"]["read_only"]
    assert services["web-panel"]["user"] == "10001"
    for name in ("web", "web-panel", "worker-inbound", "worker-outbound", "panel", "victorialogs"):
        assert services[name]["cap_drop"] == ["ALL"], name
        assert "no-new-privileges:true" in services[name]["security_opt"], name
    networks = {name: set(service.get("networks", {})) for name, service in services.items()}
    assert networks["caddy"] == {"edge"}
    assert networks["panel"] == {"panel"} and "panel" in networks["web-panel"]
    assert "edge" not in networks["web-panel"] and "panel" not in networks["web"]
    assert networks["db"] == {"data"} and networks["victorialogs"] == {"logs"}
    assert not services["db"].get("ports")
    assert not services["victorialogs"].get("ports")
    web_mounts = {mount["target"]: mount for mount in services["web"]["volumes"]}
    assert web_mounts["/run/secrets/google_sa.json"]["read_only"]
    assert web_mounts["/run/ops"]["read_only"]
    assert services["web"]["read_only"]
    assert services["web"]["user"] == "10001"
    assert services["caddy"]["user"] == "10001"
    assert services["panel"]["ports"][0]["host_ip"] == "127.0.0.1"
    assert services["panel"]["read_only"]
    assert services["panel"]["user"] == "10001"
    for worker in ("worker-inbound", "worker-outbound"):
        assert services[worker]["read_only"]
        assert not services[worker]["environment"].get("DB_OWNER_URL")
        assert not services[worker]["environment"].get("DB_READONLY_URL")
        assert not services[worker]["environment"].get("FP_OWNER_PASSWORD")
    assert not services["db"]["environment"].get("DJANGO_SECRET_KEY")
    assert not services["caddy"]["environment"].get("DB_APP_URL")


def check_panel_caddyfile() -> None:
    """The panel's own Caddy proxies to web-panel, never to the public web (ADR-020)."""
    caddyfile = (ROOT / "apps" / "panel" / "Caddyfile").read_text()
    assert "web:8000" not in caddyfile.replace("web-panel:8000", "")
    assert "web-panel:8000" in caddyfile


def check_routes(port: str | int) -> None:
    """Assert the allowlist on the proxy listening at 127.0.0.1:`port`: public routes reach
    the upstream with `X-Autobot-Edge: public`, everything else is a 404 from the proxy."""
    for path in PUBLIC_PATHS:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=3) as response:
            assert response.status == 200, path
            assert response.getheader("X-Echo-Edge") == "public", path
    for path in BLOCKED_PATHS:
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=3)
        except urllib.error.HTTPError as error:
            assert error.code == 404, path
        else:
            raise AssertionError(f"Public route leaked: {path}")


def main() -> None:
    config = subprocess.run(
        [
            "docker",
            "compose",
            "-f",
            str(ROOT / "deploy" / "compose" / "compose.yaml"),
            "-f",
            str(ROOT / "deploy" / "compose" / "compose.prod.yaml"),
            "config",
            "--format",
            "json",
        ],
        cwd=ROOT,
        env=compose_env(),
        capture_output=True,
        text=True,
        check=True,
    )
    check_compose_services(json.loads(config.stdout)["services"])
    check_panel_caddyfile()

    state = Path(tempfile.mkdtemp(prefix="fp-caddy-"))
    (state / "data").mkdir()
    (state / "config").mkdir()
    run("docker", "network", "create", NAME)
    try:
        run(
            "docker",
            "run",
            "-d",
            "--rm",
            "--network",
            NAME,
            "--name",
            BACKEND,
            "--network-alias",
            "web",
            "python:3.14-slim",
            "python",
            "-c",
            UPSTREAM_SERVER,
        )
        run(
            "docker",
            "run",
            "-d",
            "--rm",
            "--network",
            NAME,
            "--name",
            PROXY,
            "-p",
            "127.0.0.1::80",
            "-u",
            str(os.getuid()),
            "-e",
            "PUBLIC_HOST=:80",
            "-v",
            f"{ROOT / 'deploy' / 'caddy' / 'Caddyfile'}:/etc/caddy/Caddyfile:ro",
            "-v",
            f"{state / 'data'}:/data",
            "-v",
            f"{state / 'config'}:/config",
            "caddy:2",
        )
        port = run("docker", "port", PROXY, "80/tcp").rsplit(":", 1)[1]
        for _ in range(30):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1)
                break
            except urllib.error.URLError, TimeoutError, ConnectionError:
                time.sleep(0.3)
        else:
            raise RuntimeError("Caddy/upstream did not start")
        check_routes(port)
        print("Production Compose and Caddy routes: OK")
    finally:
        run("docker", "rm", "-f", PROXY, BACKEND, check=False)
        run("docker", "network", "rm", NAME, check=False)
        shutil.rmtree(state)


if __name__ == "__main__":
    main()
