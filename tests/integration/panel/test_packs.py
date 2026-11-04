"""`GET packs`, `.../schema` and `.../template` through the HTTP API (DESIGN §6.4)."""

from typing import Any

import pytest

from tests.integration.panel.conftest import get

pytestmark = [pytest.mark.django_db(transaction=True, databases=["default", "owner"])]


def test_list_packs(authed_client: Any) -> None:
    response = get(authed_client, "packs")
    assert response.status_code == 200
    names = {p["name"] for p in response.json()}
    assert {"salon", "bus"} <= names


def test_pack_schema_is_served(authed_client: Any) -> None:
    response = get(authed_client, "packs/salon/schema")
    assert response.status_code == 200
    body = response.json()
    assert "document" in body and "ui_schema" in body
    assert body["document"]["properties"]["config"] != {}


def test_pack_template_blanks_the_placeholders(authed_client: Any) -> None:
    response = get(authed_client, "packs/salon/template")
    assert response.status_code == 200
    assert response.json()["config"]["business_name"] is None


def test_unknown_pack_is_404(authed_client: Any) -> None:
    assert get(authed_client, "packs/nope/schema").status_code == 404


def test_requires_a_session(db: Any) -> None:
    from django.test import Client

    assert get(Client(), "packs").status_code == 401
