"""`channels/demo/invites.py`: redeeming and checking invite codes (D5), independent
of a particular webhook payload. The end-to-end flow through the Telegram door lives
in `test_demo.py`."""

from datetime import timedelta
from typing import Any

import pytest
from django.utils import timezone

from autobot.channels.base import InboundItem
from autobot.channels.demo import invites
from autobot.channels.demo.doors import Door
from autobot.runtime.models import Channel, DemoAccessGrant, DemoInvite
from core.messages import IncomingMessage

pytestmark = pytest.mark.django_db(transaction=True, databases=["default", "owner"])


def door(channel: Channel = Channel.DEMO_TG) -> Door:
    return Door(channel=channel, adapter=None, description=None, secrets=None, users=frozenset())  # type: ignore[arg-type]


def item(text: str, *, external_id: str = "222", phone: str | None = None) -> InboundItem:
    return InboundItem(
        provider_event_id="1",
        external_id=external_id,
        display_name=None,
        phone=phone,
        message=IncomingMessage("text", text, None, timezone.now()),
        payload={},
    )


def invite(code: str = "CODE1234", **changes: Any) -> DemoInvite:
    defaults: dict[str, Any] = {"code": code, "max_uses": 1, "created_by": "tester"}
    defaults.update(changes)
    return DemoInvite.objects.using("owner").create(**defaults)


def test_a_valid_code_grants_access_and_counts_as_a_use() -> None:
    invite()
    assert invites.redeem(door(), item("/start CODE1234"))
    assert invites.has_grant(door(), item("whatever", external_id="222"))
    assert DemoInvite.objects.using("owner").get(code="CODE1234").uses == 1
    assert (
        DemoAccessGrant.objects.using("owner").get(channel="demo_tg", external_id="222").invite_id
        == DemoInvite.objects.using("owner").get(code="CODE1234").id
    )


def test_code_is_case_insensitive_and_ignores_surrounding_space() -> None:
    invite()
    assert invites.redeem(door(), item("/start   code1234  "))


def test_a_message_without_start_is_not_a_candidate() -> None:
    invite()
    assert not invites.redeem(door(), item("CODE1234"))  # Telegram needs /start
    assert not invites.redeem(door(), item("/start"))  # no code at all


def test_whatsapp_redeems_the_code_as_the_whole_message() -> None:
    invite()
    assert invites.redeem(door(Channel.DEMO_WA), item("CODE1234", external_id="34600000000"))
    assert invites.has_grant(door(Channel.DEMO_WA), item("x", external_id="34600000000"))


def test_an_unknown_code_is_not_redeemed() -> None:
    assert not invites.redeem(door(), item("/start NOPE"))


def test_a_revoked_code_is_not_redeemed() -> None:
    invite(revoked_at=timezone.now())
    assert not invites.redeem(door(), item("/start CODE1234"))


def test_an_expired_code_is_not_redeemed() -> None:
    invite(expires_at=timezone.now() - timedelta(minutes=1))
    assert not invites.redeem(door(), item("/start CODE1234"))


def test_an_exhausted_code_is_not_redeemed_by_a_new_identity() -> None:
    invite(max_uses=1, uses=1)
    assert not invites.redeem(door(), item("/start CODE1234", external_id="222"))


def test_redeeming_again_with_the_same_identity_refreshes_without_another_use() -> None:
    invite(max_uses=1)
    assert invites.redeem(door(), item("/start CODE1234", external_id="222"))
    # Still "valid" by max_uses alone it would now refuse a *different* identity, but
    # the same one redeeming again must only refresh its own grant.
    assert invites.redeem(door(), item("/start CODE1234", external_id="222"))
    assert DemoInvite.objects.using("owner").get(code="CODE1234").uses == 1


def test_a_grant_is_scoped_to_its_door() -> None:
    invite(max_uses=2)
    assert invites.redeem(door(Channel.DEMO_TG), item("/start CODE1234", external_id="222"))
    assert not invites.has_grant(door(Channel.DEMO_WA), item("x", external_id="222"))


def test_has_grant_also_matches_a_whatsapp_phone_without_the_plus() -> None:
    invite()
    assert invites.redeem(door(Channel.DEMO_WA), item("CODE1234", external_id="34600000000"))
    assert invites.has_grant(
        door(Channel.DEMO_WA), item("x", external_id="other-bsuid", phone="+34600000000")
    )


def test_has_grant_ignores_an_expired_grant() -> None:
    invite(expires_at=timezone.now() + timedelta(days=1))
    assert invites.redeem(door(), item("/start CODE1234", external_id="222"))
    DemoAccessGrant.objects.using("owner").filter(external_id="222").update(
        expires_at=timezone.now() - timedelta(minutes=1)
    )
    assert not invites.has_grant(door(), item("x", external_id="222"))
