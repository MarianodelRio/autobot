"""`GET /calendar/service-account` (D1)."""

from typing import Any

import pytest

from tests.platform.panel.conftest import get

pytestmark = [pytest.mark.django_db(transaction=True, databases=["default", "owner"])]


def test_not_configured_when_the_server_has_no_service_account(
    authed_client: Any, settings: Any
) -> None:
    settings.GOOGLE_SERVICE_ACCOUNT_FILE = ""
    response = get(authed_client, "calendar/service-account")
    assert response.status_code == 200
    assert response.json() == {"configured": False, "email": None}


def test_configured_but_unreadable_file_reports_no_email(authed_client: Any, settings: Any) -> None:
    settings.GOOGLE_SERVICE_ACCOUNT_FILE = "/does/not/exist.json"
    response = get(authed_client, "calendar/service-account")
    assert response.status_code == 200
    assert response.json() == {"configured": True, "email": None}


def test_returns_the_email_without_the_private_key(
    authed_client: Any, settings: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from unittest.mock import MagicMock

    from google.oauth2 import service_account

    settings.GOOGLE_SERVICE_ACCOUNT_FILE = "d1-panel-test-sa.json"
    monkeypatch.setattr(
        service_account.Credentials,
        "from_service_account_file",
        lambda *a, **k: MagicMock(service_account_email="autobot@proyecto.iam.gserviceaccount.com"),
    )
    response = get(authed_client, "calendar/service-account")
    assert response.status_code == 200
    body = response.json()
    assert body == {"configured": True, "email": "autobot@proyecto.iam.gserviceaccount.com"}


def test_requires_a_session(db: Any) -> None:
    from django.test import Client

    assert get(Client(), "calendar/service-account").status_code == 401
