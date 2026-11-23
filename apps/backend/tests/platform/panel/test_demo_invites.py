"""HTTP contract for demo invite codes: create, list, revoke and the QR/link
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
    assert len(body["code"]) >= 8
    assert all(c not in body["code"] for c in "0O1IL")  # no ambiguous characters

    listed = get(authed_client, "demo/invites").json()
    assert [i["id"] for i in listed["items"]] == [body["id"]] and listed["next_cursor"] is None

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
    assert "qr_svg" not in without  # the list/create never carry the QR
    assert get(authed_client, f"demo/invites/{without['id']}/qr").json() == {"qr_svg": None}

    settings.DEMO_TELEGRAM_BOT_USERNAME = "AutobotDemoBot"
    with_username = post(authed_client, "demo/invites", {"expires_in_days": 1}).json()
    assert with_username["telegram_link"] == (
        f"https://t.me/AutobotDemoBot?start={with_username['code']}"
    )
    qr = get(authed_client, f"demo/invites/{with_username['id']}/qr").json()
    assert qr["qr_svg"] is not None and "<svg" in qr["qr_svg"]


def test_note_is_capped_at_200(authed_client: Any) -> None:
    ok = post(authed_client, "demo/invites", {"note": "x" * 200, "expires_in_days": 1})
    assert ok.status_code == 200
    long = post(authed_client, "demo/invites", {"note": "x" * 201, "expires_in_days": 1})
    assert long.status_code == 422


def test_list_is_paginated_with_grants_counted_in_one_query(authed_client: Any) -> None:
    for _ in range(3):
        post(authed_client, "demo/invites", {"expires_in_days": None})
    page = get(authed_client, "demo/invites?limit=2").json()
    rest = get(authed_client, f"demo/invites?limit=2&cursor={page['next_cursor']}").json()
    assert (len(page["items"]), len(rest["items"]), rest["next_cursor"]) == (2, 1, None)
    ids = [i["id"] for i in page["items"] + rest["items"]]
    assert len(set(ids)) == 3
    assert get(authed_client, "demo/invites?cursor=garbage").status_code == 400
    assert get(authed_client, "demo/invites?limit=0").status_code == 422


def test_creation_and_its_audit_row_roll_back_together(
    authed_client: Any, monkeypatch: Any
) -> None:
    from autobot.panel.services import demo_invites

    def boom(**kwargs: Any) -> None:
        raise RuntimeError("audit down")

    monkeypatch.setattr(demo_invites, "record", boom)
    with pytest.raises(RuntimeError):
        demo_invites.create_invite(note="x", max_uses=1, expires_in_days=None, actor="op")
    assert DemoInvite.objects.using("owner").count() == 0


def test_grants_count_reflects_redemptions(authed_client: Any) -> None:
    created = post(authed_client, "demo/invites", {"max_uses": 2, "expires_in_days": None}).json()
    invite = DemoInvite.objects.using("owner").get(id=created["id"])
    DemoAccessGrant.objects.using("owner").create(
        channel="demo_tg", external_id="1", invite=invite, granted_at=timezone.now()
    )
    listed = get(authed_client, "demo/invites").json()
    assert listed["items"][0]["grants"] == 1
