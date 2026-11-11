"""The runtime reads versioned config and encrypted secrets through fp_app."""

from typing import Any

import pytest
from django.db import OperationalError
from django.test import Client

from autobot.ops.logging import redact
from autobot.tenancy.models import TenantSecret
from autobot.tenancy.registry import (
    get_registry,
    load_registry,
    reset_registry,
    sources_from_database,
)
from tests.helpers.integration import tg_tenant
from tests.platform.tenancy.helpers import PACKS, TG_SECRETS, seed_db

pytestmark = pytest.mark.django_db(transaction=True, databases=["default", "owner"])


@pytest.fixture(autouse=True)
def reset() -> Any:
    reset_registry()
    yield
    reset_registry()


def test_database_current_versions_and_query_count(django_assert_num_queries: Any) -> None:
    doc = tg_tenant()
    seed_db(
        doc, secrets={doc["slug"]: TG_SECRETS}, datasets={doc["slug"]: {"rows": {"a.csv": "old"}}}
    )
    seed_db({**doc, "name": "Updated"}, datasets={doc["slug"]: {"rows": {"a.csv": "new"}}})
    with django_assert_num_queries(7):
        revision, sources = sources_from_database()
    assert revision == 2 and len(sources) == 1
    source = sources[0]
    assert source.version == 2 and source.document["name"] == "Updated"
    assert source.secrets == TG_SECRETS
    assert source.datasets == {"rows": {"a.csv": "new"}}
    assert TG_SECRETS["bot_token"] not in repr(source)
    registry = load_registry(sources, PACKS)
    assert registry.problems == {} and registry.tenants[0].main_enabled


def test_corrupt_secret_only_disables_its_channel() -> None:
    doc = tg_tenant()
    seed_db(doc, secrets={doc["slug"]: TG_SECRETS})
    TenantSecret.objects.using("owner").filter(tenant_id=doc["id"]).update(
        ciphertext=b"private-bad-token"
    )
    _, sources = sources_from_database()
    registry = load_registry(sources, PACKS)
    assert registry.problems == {}
    (tenant,) = registry.tenants
    assert not tenant.is_degraded and not tenant.main_enabled
    assert "secrets cannot be decrypted" in tenant.main_disabled


def test_redaction_has_no_queries(tenants: Any, django_assert_num_queries: Any) -> None:
    doc = tg_tenant()
    tenants(doc)
    get_registry()
    with django_assert_num_queries(0):
        assert redact(TG_SECRETS["bot_token"]) == "[REDACTED]"


def test_health_catches_initial_registry_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(alias: str = "default") -> Any:
        raise OperationalError("private database failure")

    monkeypatch.setattr("autobot.tenancy.registry.sources_from_database", fail)
    response = Client().get("/health")
    assert response.status_code == 503
    assert response.json() == {"status": "error"}  # public: no detail
    assert b"private database failure" not in response.content

    internal = Client().get("/health/internal")
    assert internal.status_code == 503
    assert internal.json()["database"] is False
    assert b"private database failure" not in internal.content


@pytest.mark.parametrize("kind", ["whatsapp", "telegram"])
def test_webhook_retries_when_initial_registry_load_fails(
    kind: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(alias: str = "default") -> Any:
        raise OperationalError("private database failure")

    monkeypatch.setattr("autobot.tenancy.registry.sources_from_database", fail)
    response = Client().post(f"/webhooks/{kind}/missingpublic")
    assert response.status_code == 503
    assert b"private database failure" not in response.content
