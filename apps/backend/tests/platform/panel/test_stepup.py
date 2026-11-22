"""Step-up reauthentication and the idle timeout of the panel session."""

import time
from typing import Any

import pytest
from django.test import Client
from django_otp.oath import totp  # type: ignore[import-untyped]
from django_otp.plugins.otp_totp.models import TOTPDevice  # type: ignore[import-untyped]

from autobot.ops.models import AuditEvent
from autobot.panel import stepup
from autobot.panel.auth import IDLE_TIMEOUT_S, LAST_SEEN_KEY
from tests.helpers.integration import tg_tenant, wa_tenant
from tests.platform.panel.conftest import HOST, get, next_otp, post

pytestmark = [
    pytest.mark.django_db(transaction=True, databases=["default", "owner"]),
    pytest.mark.usefixtures("clean_jobs"),
]


def assert_reauth_required(response: Any) -> None:
    assert response.status_code == 403
    assert response.json()["code"] == "reauth_required"


def put(client: Client, path: str, data: dict[str, Any]) -> Any:
    import json

    return client.put(
        f"/api/panel/{path}", data=json.dumps(data), content_type="application/json", HTTP_HOST=HOST
    )


def sensitive_calls(client: Client, tenants: Any) -> list[Any]:
    from uuid import uuid4

    tenants(tg_tenant("tg"))
    return [
        post(client, "tenants/tg/delete", {"confirm_slug": "tg"}),
        post(client, "tenants/tg/export"),
        post(client, "tenants/tg/rollback", {"version": 1, "comment": "undo"}),
        post(client, "tenants/tg/status", {"action": "activate", "confirm_slug": "tg"}),
        put(client, "tenants/tg/secrets", {"secrets": {}}),
        get(client, f"contacts/{uuid4()}/export"),
        post(client, f"contacts/{uuid4()}/forget"),
    ]


def test_sensitive_actions_require_step_up(authed_client: Client, tenants: Any) -> None:
    for response in sensitive_calls(authed_client, tenants):
        assert_reauth_required(response)


def test_pause_does_not_need_step_up(authed_client: Client, tenants: Any) -> None:
    tenants(wa_tenant("a"))
    response = post(authed_client, "tenants/a/status", {"action": "pause"})
    assert response.status_code != 403 or response.json()["code"] != "reauth_required"


def test_step_up_unlocks_the_actions(reauthed_client: Client, tenants: Any) -> None:
    for response in sensitive_calls(reauthed_client, tenants):
        assert response.status_code != 403 or response.json()["code"] != "reauth_required"
    assert AuditEvent.objects.using("owner").filter(action="auth.step_up").count() == 1


def test_step_up_rejects_a_reused_code(authed_client: Client, user: Any) -> None:
    device = TOTPDevice.objects.using("owner").get(user=user)
    otp = next_otp(user)
    first = post(authed_client, "auth/step-up", {"otp": otp})
    assert first.status_code == 200, first.content
    again = post(authed_client, "auth/step-up", {"otp": otp})
    assert again.status_code == 403 and again.json()["code"] == "invalid_otp"
    # The code the login consumed is not valid for a step-up either.
    used = str(totp(device.bin_key)).zfill(6)
    assert post(authed_client, "auth/step-up", {"otp": used}).status_code == 403


def test_step_up_wrong_code_is_audited_and_limited(authed_client: Client, user: Any) -> None:
    for _ in range(5):
        assert post(authed_client, "auth/step-up", {"otp": "000000"}).status_code == 403
    blocked = post(authed_client, "auth/step-up", {"otp": "000000"})
    assert blocked.status_code == 429
    events = AuditEvent.objects.using("owner")
    assert events.filter(action="auth.step_up_failed").count() == 5
    assert events.filter(action="auth.step_up_blocked").count() == 1


def test_step_up_needs_a_session() -> None:
    assert post(Client(), "auth/step-up", {"otp": "123456"}).status_code in (401, 403)


def test_step_up_expires_after_five_minutes(
    reauthed_client: Client, tenants: Any, monkeypatch: Any
) -> None:
    tenants(tg_tenant("tg"))
    now = time.time()
    monkeypatch.setattr(time, "time", lambda: now + stepup.REAUTH_MAX_AGE_S - 5)
    assert post(reauthed_client, "tenants/tg/export").status_code == 200
    monkeypatch.setattr(time, "time", lambda: now + stepup.REAUTH_MAX_AGE_S + 5)
    assert_reauth_required(post(reauthed_client, "tenants/tg/export"))


def test_idle_session_expires_after_thirty_minutes(authed_client: Client) -> None:
    assert get(authed_client, "auth/me").status_code == 200
    session = authed_client.session
    session[LAST_SEEN_KEY] = time.time() - IDLE_TIMEOUT_S - 5
    session.save()
    assert get(authed_client, "auth/me").status_code == 401
    # The session is gone, not just refused once.
    assert get(authed_client, "auth/me").status_code == 401


def test_activity_keeps_the_session_alive(authed_client: Client) -> None:
    session = authed_client.session
    session[LAST_SEEN_KEY] = time.time() - IDLE_TIMEOUT_S + 60
    session.save()
    assert get(authed_client, "auth/me").status_code == 200
    assert authed_client.session[LAST_SEEN_KEY] > time.time() - 30
