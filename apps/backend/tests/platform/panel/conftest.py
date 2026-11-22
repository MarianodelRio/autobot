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


def next_otp(user: Any) -> str:
    """The code of the next 30 s window: the login already used the current one and a
    TOTP code is never accepted twice (the device's `last_t`). Counted from the device's
    stored drift, which a login near a window boundary shifts by one."""
    device = TOTPDevice.objects.using("owner").get(user=user)
    return str(totp(device.bin_key, drift=device.drift + 1)).zfill(6)


def step_up(client: Client, user: Any) -> Any:
    return post(client, "auth/step-up", {"otp": next_otp(user)})


@pytest.fixture
def reauthed_client(authed_client: Client, user: Any) -> Client:
    """A logged-in client that has just passed the step-up."""
    assert step_up(authed_client, user).status_code == 200
    return authed_client
