"""Fixtures of the runtime integration tests (tests/integration/helpers.py has the rest)."""

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from django.core.management import call_command
from django.db import connections
from pytest_django import Settings

from flowpilot.channels import views
from flowpilot.channels.ratelimit import WindowLimiter
from flowpilot.runtime import process
from flowpilot.tenancy.registry import get_registry
from tests.tenancy.helpers import PACKS, TG_SECRETS, WA_SECRETS, write_secrets, write_tenants


@pytest.fixture
def tenants(tmp_path: Path, settings: Settings, monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    """Write tenants and secrets, load the registry and sync the tenant rows. The
    in-memory limits start empty."""
    settings.TENANTS_DIR = tmp_path / "tenants"
    settings.SECRETS_FILE = tmp_path / "secrets.yaml"
    monkeypatch.setattr("packs.registry.PACKS", PACKS)
    monkeypatch.setattr(views, "limiter", WindowLimiter())
    monkeypatch.setattr(process, "contact_limiter", WindowLimiter(limit=20, window_s=60))

    def setup(*docs: dict[str, Any], secrets: dict[str, Any] | None = None) -> None:
        write_tenants(tmp_path, *docs)
        default = {
            d["slug"]: WA_SECRETS if d["channel"]["type"] == "whatsapp" else TG_SECRETS
            for d in docs
            if "channel" in d  # a demo tenant has none
        }
        write_secrets(tmp_path, default if secrets is None else secrets)
        get_registry.cache_clear()
        call_command("sync_tenants", stdout=None)

    yield setup
    get_registry.cache_clear()


@pytest.fixture
def clean_jobs(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """The flush does not reach Procrastinate's tables (unmanaged models)."""
    from flowpilot.jobs import app

    # Worker tests may cross a five-minute boundary and automatically enqueue this
    # new platform periodic. Its service checks have their own mocked integration
    # tests; unrelated runtime workers must never query external health endpoints.
    monkeypatch.setattr(app.tasks["ops_check"], "func", lambda timestamp: None)
    yield
    with connections["owner"].cursor() as cursor:
        # Periodic defers reference their job: they go first.
        cursor.execute("DELETE FROM procrastinate_periodic_defers")
        cursor.execute("DELETE FROM procrastinate_jobs")


from tests.integration.salon_helpers import salon_setup  # noqa: F401, E402
