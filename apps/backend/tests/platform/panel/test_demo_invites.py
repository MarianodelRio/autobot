"""HTTP contract for demo invite codes (D5): create, list, revoke and the QR/link
each one carries."""

from typing import Any

import pytest
from django.utils import timezone

from autobot.runtime.models import DemoAccessGrant, DemoInvite
from tests.platform.panel.conftest import get, post

pytestmark = pytest.mark.django_db(transaction=True, databases=["default", "owner"])


def test_create_list_and_revoke(authed_client: Any) -> None:
    created = post(
        authed_client,
        "demo/invites",
        {"note": "peluquero Juan", "max_uses": 2, "expires_in_days": 7},
    )
    assert created.status_code == 200, created.content
    body = created.json()
    assert body["note"] == "peluquero Juan"
    assert body["max_uses"] == 2
    assert body["uses"] == 0
    assert body["grants"] == 0
    assert body["revoked_at"] is None
    assert len(body["code"]) == 8
    assert all(c not in body["code"] for c in "0O1IL")  # no ambiguous characters

    listed = get(authed_client, "demo/invites").json()
    assert [i["id"] for i in listed] == [body["id"]]

    revoked = post(authed_client, f"demo/invites/{body['id']}/revoke")
    assert revoked.status_code == 200, revoked.content
    assert revoked.json()["revoked_at"] is not None

    assert post(authed_client, f"demo/invites/{body['id']}/revoke").status_code == 409


def test_revoking_an_unknown_invite_is_a_404(authed_client: Any) -> None:
    assert (
        post(authed_client, "demo/invites/01a1e5a0-0000-7000-8000-000000000000/revoke").status_code
        == 404
    )


def test_max_uses_and_expires_in_days_are_bounded(authed_client: Any) -> None:
    assert (
        post(authed_client, "demo/invites", {"max_uses": 0, "expires_in_days": 7}).status_code
        == 422
    )
    assert (
        post(authed_client, "demo/invites", {"max_uses": 1, "expires_in_days": 0}).status_code
        == 422
    )
    assert (
        post(authed_client, "demo/invites", {"max_uses": 1, "expires_in_days": None}).status_code
        == 200
    )


def test_link_and_qr_only_appear_with_a_configured_bot_username(
    authed_client: Any, settings: Any
) -> None:
    settings.DEMO_TELEGRAM_BOT_USERNAME = ""
    without = post(authed_client, "demo/invites", {"expires_in_days": 1}).json()
    assert without["telegram_link"] is None
    assert without["qr_svg"] is None

    settings.DEMO_TELEGRAM_BOT_USERNAME = "AutobotDemoBot"
    with_username = post(authed_client, "demo/invites", {"expires_in_days": 1}).json()
    assert with_username["telegram_link"] == (
        f"https://t.me/AutobotDemoBot?start={with_username['code']}"
    )
    assert with_username["qr_svg"] is not None and "<svg" in with_username["qr_svg"]


def test_grants_count_reflects_redemptions(authed_client: Any) -> None:
    created = post(authed_client, "demo/invites", {"max_uses": 2, "expires_in_days": None}).json()
    invite = DemoInvite.objects.using("owner").get(id=created["id"])
    DemoAccessGrant.objects.using("owner").create(
        channel="demo_tg", external_id="1", invite=invite, granted_at=timezone.now()
    )
    listed = get(authed_client, "demo/invites").json()
    assert listed[0]["grants"] == 1
