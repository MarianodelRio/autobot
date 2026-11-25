"""Every panel request reads the configuration as the database has it now (ADR-030):
a save made through another gunicorn worker is never answered with the old data."""

from typing import Any

import pytest
from django.test import Client

from autobot.tenancy import registry
from tests.helpers.integration import wa_tenant
from tests.platform.panel.conftest import get
from tests.platform.tenancy.helpers import seed_db

pytestmark = pytest.mark.django_db(transaction=True, databases=["default", "owner"])


def written_elsewhere(doc: dict[str, Any], **changes: Any) -> None:
    """A save made by another worker: this process's registry is not told."""
    seed_db({**doc, **changes}, reset=False)
    assert registry.loaded_registry() is not None and registry._revision is not None


def test_detail_and_setup_see_a_save_made_through_another_worker(
    authed_client: Client, tenants: Any
) -> None:
    doc = wa_tenant("a")
    tenants(doc)
    assert get(authed_client, "tenants/a").json()["name"] == "A"  # this worker has loaded it
    written_elsewhere(doc, name="Renamed")
    # Still inside the polling window of this worker: its own snapshot is the old one.
    assert registry.get_registry().by_slug["a"].document.name == "A"
    detail = get(authed_client, "tenants/a")
    assert detail.status_code == 200 and detail.json()["name"] == "Renamed"
    assert get(authed_client, "tenants/a/setup").status_code == 200


def test_a_tenant_renamed_elsewhere_is_found_by_its_new_slug(
    authed_client: Client, tenants: Any
) -> None:
    doc = wa_tenant("a")
    tenants(doc)
    assert get(authed_client, "tenants/a").status_code == 200
    written_elsewhere(doc, slug="b")
    assert get(authed_client, "tenants/b").status_code == 200
    assert get(authed_client, "tenants/a").status_code == 404


def test_public_paths_do_not_check_the_revision(
    tenants: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    tenants(wa_tenant("a"))
    registry.get_registry()
    reads = []

    def read() -> int:
        reads.append(1)
        return 1

    monkeypatch.setattr(registry, "_read_revision", read)
    assert Client().get("/health").status_code == 200
    assert reads == []
