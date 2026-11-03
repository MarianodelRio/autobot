"""Fixtures of the runtime integration tests (tests/integration/helpers.py has the rest)."""

from collections.abc import Iterator
from typing import Any

import pytest
from django.db import connections

from autobot.channels import views
from autobot.channels.ratelimit import WindowLimiter
from autobot.runtime import process
from autobot.tenancy.registry import reset_registry
from tests.tenancy.helpers import PACKS, TG_SECRETS, WA_SECRETS, seed_db


@pytest.fixture
def tenants(monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    """Seed versioned config and encrypted secrets, resetting the runtime limits."""
    monkeypatch.setattr("packs.registry.PACKS", PACKS)
    monkeypatch.setattr(views, "limiter", WindowLimiter())
    monkeypatch.setattr(process, "contact_limiter", WindowLimiter(limit=20, window_s=60))

    def setup(*docs: dict[str, Any], secrets: dict[str, Any] | None = None) -> None:
        default = {
            d["slug"]: WA_SECRETS if d["channel"]["type"] == "whatsapp" else TG_SECRETS
            for d in docs
            if "channel" in d  # a demo tenant has none
        }
        seed_db(*docs, secrets=default if secrets is None else secrets)

    yield setup
    reset_registry()


@pytest.fixture
def clean_jobs(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """The flush does not reach Procrastinate's tables (unmanaged models)."""
    from autobot.jobs import app

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
