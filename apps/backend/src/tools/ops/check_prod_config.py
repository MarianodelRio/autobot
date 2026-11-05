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

from cryptography.fernet import Fernet

ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent.parent
NAME = f"fp-config-{uuid.uuid4().hex[:12]}"
BACKEND = f"{NAME}-backend"
PROXY = f"{NAME}-caddy"


def run(*args: str, check: bool = True) -> str:
    result = subprocess.run(args, capture_output=True, text=True, check=False)
    if check and result.returncode:
        raise RuntimeError(f"{' '.join(args[:3])}: {result.stderr.strip()}")
    return result.stdout.strip()


def main() -> None:
    env = {
        **os.environ,
        "SECRETS_ENCRYPTION_KEY": Fernet.generate_key().decode(),
        "SHA": "a" * 40,
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
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    services = json.loads(config.stdout)["services"]
    assert services["web"]["ports"][0]["host_ip"] == "127.0.0.1"
    assert not services["db"].get("ports")
    assert not services["victorialogs"].get("ports")
    web_mounts = {mount["target"]: mount for mount in services["web"]["volumes"]}
    assert web_mounts["/run/secrets/google_sa.json"]["read_only"]
    assert web_mounts["/run/ops"]["read_only"]
    assert services["web"]["read_only"] and services["worker"]["read_only"]
    assert services["web"]["user"] == "10001"
    assert services["caddy"]["user"] == "10001"
    assert services["panel"]["ports"][0]["host_ip"] == "127.0.0.1"
    assert services["panel"]["read_only"]
    assert services["panel"]["user"] == "10001"
    assert not services["worker"]["environment"].get("DB_OWNER_URL")
    assert not services["worker"]["environment"].get("DB_READONLY_URL")
    assert not services["worker"]["environment"].get("FP_OWNER_PASSWORD")
    assert not services["db"]["environment"].get("DJANGO_SECRET_KEY")
    assert not services["caddy"]["environment"].get("DB_APP_URL")

    state = Path(tempfile.mkdtemp(prefix="fp-caddy-"))
    (state / "data").mkdir()
    (state / "config").mkdir()
    run("docker", "network", "create", NAME)
    try:
        # Every upstream path returns 200: a 404 can only come from Caddy. Echoes
        # X-Autobot-Edge back so the test can check Caddy actually set it.
        server = (
            "from http.server import BaseHTTPRequestHandler,HTTPServer; "
            "H=type('H',(BaseHTTPRequestHandler,),{'do_GET':lambda s:"
            "(s.send_response(200),"
            "s.send_header('X-Echo-Edge', s.headers.get('X-Autobot-Edge','')),"
            "s.end_headers())}); "
            "HTTPServer(('0.0.0.0',8000),H).serve_forever()"
        )
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
            server,
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
        for path in (
            "/health",
            "/webhooks/telegram-demo",
            "/webhooks/whatsapp-demo",
            "/webhooks/telegram/abc",
            "/webhooks/whatsapp/abc",
        ):
            with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=3) as response:
                assert response.status == 200, path
                assert response.getheader("X-Echo-Edge") == "public", path
        for path in (
            "/",
            "/admin/",
            "/static/admin/css/base.css",
            "/health/",
            "/webhooks/telegram",
            "/webhooks/telegram-test",
        ):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=3)
            except urllib.error.HTTPError as error:
                assert error.code == 404, path
            else:
                raise AssertionError(f"Public route leaked: {path}")
        print("Production Compose and Caddy routes: OK")
    finally:
        run("docker", "rm", "-f", PROXY, BACKEND, check=False)
        run("docker", "network", "rm", NAME, check=False)
        shutil.rmtree(state)


if __name__ == "__main__":
    main()
