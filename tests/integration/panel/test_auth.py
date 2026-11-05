"""Panel login: session + confirmed TOTP, CSRF-checked writes, and the public edge
and `owner`-less gates. Every request names its host explicitly:
the panel is only ever reached at 127.0.0.1, through the SSH tunnel (ADR-008)."""

import hashlib
import hmac
import io
import json
from typing import Any
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db import connections
from django.test import Client
from django.test.utils import CaptureQueriesContext
from django_otp.oath import totp  # type: ignore[import-untyped]
from django_otp.plugins.otp_totp.models import TOTPDevice  # type: ignore[import-untyped]

from autobot.ops.models import AuditEvent
from tests.integration.helpers import fixture, wa_tenant
from tests.tenancy.helpers import WA_SECRETS

pytestmark = [
    pytest.mark.django_db(transaction=True, databases=["default", "owner"]),
    pytest.mark.usefixtures("clean_jobs"),
]

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


def otp_for(username: str) -> str:
    device = TOTPDevice.objects.using("owner").get(user__username=username)
    return str(totp(device.bin_key)).zfill(6)


def csrf(client: Client) -> str:
    response = client.get("/api/panel/auth/csrf", HTTP_HOST=HOST)
    assert response.status_code == 200
    return response.cookies["autobot_panel_csrftoken"].value


def post(client: Client, path: str, payload: dict[str, Any], token: str | None = None) -> Any:
    headers = {"X-CSRFToken": token} if token else None
    return client.post(
        f"/api/panel/{path}",
        data=json.dumps(payload),
        content_type="application/json",
        headers=headers,
        HTTP_HOST=HOST,
    )


def get(client: Client, path: str, headers: dict[str, str] | None = None) -> Any:
    return client.get(f"/api/panel/{path}", headers=headers, HTTP_HOST=HOST)


def login(
    client: Client,
    token: str | None = None,
    *,
    username: str = "operator",
    password: str = PASSWORD,
    otp: str | None = None,
) -> Any:
    return post(
        client,
        "auth/login",
        {"username": username, "password": password, "otp": otp or otp_for(username)},
        token,
    )


def test_login_succeeds_and_me_reflects_the_session(user: Any) -> None:
    client = Client(enforce_csrf_checks=True)
    response = login(client, csrf(client))
    assert response.status_code == 200
    assert response.json() == {"username": "operator"}
    assert get(client, "auth/me").json() == {"username": "operator"}


@pytest.mark.parametrize(
    "credentials",
    [
        {"password": "wrong-password", "otp_is": "valid"},
        {"password": PASSWORD, "otp_is": "bad"},
        {"password": PASSWORD, "otp_is": "no-device"},
    ],
)
def test_bad_credentials_bad_otp_or_no_device_are_generic_401(
    user: Any, credentials: dict[str, str]
) -> None:
    if credentials["otp_is"] == "no-device":
        TOTPDevice.objects.using("owner").filter(user=user).delete()
        otp = "123456"
    elif credentials["otp_is"] == "bad":
        otp = "000000"
    else:
        otp = otp_for("operator")
    client = Client(enforce_csrf_checks=True)
    response = login(client, csrf(client), password=credentials["password"], otp=otp)
    assert response.status_code == 401
    assert response.json() == {"detail": "Credenciales no válidas."}


def test_lockout_after_five_failures(user: Any) -> None:
    client = Client(enforce_csrf_checks=True)
    token = csrf(client)
    for _ in range(5):
        response = login(client, token, password="wrong", otp="000000")
        assert response.status_code == 401
    # The 6th attempt uses the right credentials, but the lockout still blocks it.
    assert login(client, token).status_code == 401
    assert AuditEvent.objects.using("owner").filter(action="auth.login_failed").count() == 6


def test_me_without_session_is_401(user: Any) -> None:
    client = Client()
    assert get(client, "auth/me").status_code == 401


def test_session_without_otp_is_401(user: Any) -> None:
    client = Client()
    client.force_login(user)
    assert get(client, "auth/me").status_code == 401


def test_post_without_csrf_is_403_including_login(user: Any) -> None:
    client = Client(enforce_csrf_checks=True)
    assert login(client).status_code == 403
    client.force_login(user)
    assert post(client, "auth/logout", {}).status_code == 403


def test_public_edge_header_is_404(user: Any) -> None:
    client = Client()
    client.force_login(user)
    response = get(client, "auth/me", headers={"X-Autobot-Edge": "public"})
    assert response.status_code == 404


@pytest.mark.filterwarnings("ignore:Overriding setting DATABASES")
def test_without_owner_alias_is_503(settings: Any) -> None:
    settings.DATABASES = {
        name: value for name, value in settings.DATABASES.items() if name != "owner"
    }
    response = get(Client(), "auth/me")
    assert response.status_code == 503


def test_logout_clears_the_session(user: Any) -> None:
    client = Client(enforce_csrf_checks=True)
    login(client, csrf(client))
    token = client.cookies["autobot_panel_csrftoken"].value
    response = post(client, "auth/logout", {}, token)
    assert response.status_code == 200
    assert get(client, "auth/me").status_code == 401


def test_login_is_audited(user: Any) -> None:
    client = Client(enforce_csrf_checks=True)
    login(client, csrf(client))
    event = AuditEvent.objects.using("owner").get(action="auth.login")
    assert event.actor == "operator" and "operator" in event.summary


def test_fp_app_cannot_read_auth_user() -> None:
    with (
        pytest.raises(Exception, match="permission denied"),
        connections["default"].cursor() as cursor,
    ):
        cursor.execute("SELECT 1 FROM auth_user LIMIT 1")


def test_webhook_never_queries_a_session_table(tenants: Any) -> None:
    tenants(wa_tenant())
    body = fixture("whatsapp/text.json")
    signature = (
        "sha256=" + hmac.new(WA_SECRETS["app_secret"].encode(), body, hashlib.sha256).hexdigest()
    )
    with CaptureQueriesContext(connections["owner"]) as queries:
        response = Client().post(
            "/webhooks/whatsapp/pubwa0000",
            data=body,
            content_type="application/json",
            headers={"X-Hub-Signature-256": signature},
            REMOTE_ADDR="203.0.113.1",
        )
    assert response.status_code == 200
    assert list(queries) == []


def test_panel_user_create_with_patched_getpass() -> None:
    with patch("getpass.getpass", side_effect=[PASSWORD, PASSWORD]):
        out = io.StringIO()
        call_command("panel_user", "create", "newop", stdout=out)
    assert User.objects.using("owner").filter(username="newop", is_staff=True).exists()
    device = TOTPDevice.objects.using("owner").get(user__username="newop")
    assert device.confirmed
    assert "otpauth://totp/" in out.getvalue()


def test_panel_user_exists(user: Any) -> None:
    call_command("panel_user", "exists", "operator")
    with pytest.raises(Exception, match="No existe"):
        call_command("panel_user", "exists", "nobody")
