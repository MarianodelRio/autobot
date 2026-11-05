"""Shared panel-API auth helpers for T16a's read-only routers (`test_auth.py` keeps
its own, more detailed, login fixtures for the auth flow itself)."""

import json
from typing import Any

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django_otp.oath import totp  # type: ignore[import-untyped]
from django_otp.plugins.otp_totp.models import TOTPDevice  # type: ignore[import-untyped]

HOST = "127.0.0.1"
PASSWORD = "Sup3r-Secret-Panel-42"
User = get_user_model()


@pytest.fixture
def user() -> Any:
    created = User.objects.db_manager("owner").create_user(
        username="operator", password=PASSWORD, is_staff=True
    )
    TOTPDevice.objects.using("owner").create(user=created, name="default", confirmed=True)
    return created


def get(client: Client, path: str) -> Any:
    return client.get(f"/api/panel/{path}", HTTP_HOST=HOST)


def post(client: Client, path: str, payload: dict[str, Any] | None = None) -> Any:
    return client.post(
        f"/api/panel/{path}",
        data=json.dumps(payload or {}),
        content_type="application/json",
        HTTP_HOST=HOST,
    )


@pytest.fixture
def authed_client(user: Any) -> Client:
    client = Client()
    client.get("/api/panel/auth/csrf", HTTP_HOST=HOST)
    device = TOTPDevice.objects.using("owner").get(user=user)
    otp = str(totp(device.bin_key)).zfill(6)
    response = client.post(
        "/api/panel/auth/login",
        data=json.dumps({"username": user.username, "password": PASSWORD, "otp": otp}),
        content_type="application/json",
        HTTP_HOST=HOST,
    )
    assert response.status_code == 200
    return client
