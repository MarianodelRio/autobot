"""The demo bot's Telegram door and its business selector, with the toy pack, the
real database and Telegram answered by a mock transport. Covers who may use it (the
closed `DEMO_TELEGRAM_USERS` list), picking and switching demo businesses, businesses
that stop being available, and the isolation of demo doors: never a real tenant's main
channel, and the owner's notices reach it like a real tenant's. The WhatsApp door
(always off in this file, since its settings are never configured here) has its own
scenarios in test_demo_whatsapp.py."""

import json
from collections.abc import Iterator
from typing import Any

import pytest
from django.test import Client
from pytest_django import Settings

from flowpilot.channels.demo import selector
from flowpilot.channels.demo.doors import door
from flowpilot.channels.ratelimit import WindowLimiter
from flowpilot.runtime.models import Contact, DemoEvent, InboundEvent, Notification, OutboundMessage
from flowpilot.tenancy.registry import get_registry
from tests.integration.helpers import (
    TELEGRAM_DEMO_URL,
    Providers,
    demo_tenant,
    drain,
    jobs,
    providers,
    tg_tenant,
    wa_tenant,
)

__all__ = ["providers"]  # re-exported fixture

pytestmark = [
    pytest.mark.django_db(transaction=True, databases=["default", "owner"]),
    pytest.mark.usefixtures("clean_jobs"),
]

USER = 1  # in DEMO_TELEGRAM_USERS
STRANGER = 222
SECRET = "t" * 32
URL = TELEGRAM_DEMO_URL
_ids = iter(range(900_000_001, 999_999_999))


@pytest.fixture(autouse=True)
def demo_door(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(selector, "refusals", WindowLimiter(limit=3, window_s=3600))
    settings.DEMO_TELEGRAM_TOKEN = "999:TEST-TOKEN"
    settings.DEMO_TELEGRAM_WEBHOOK_SECRET = SECRET
    settings.DEMO_TELEGRAM_USERS = frozenset({USER})
    door.cache_clear()
    yield
    door.cache_clear()


def user(user_id: int) -> dict[str, Any]:
    return {"id": user_id, "is_bot": False, "first_name": "Tester"}


def say(user_id: int, text: str) -> int:
    update = {
        "update_id": next(_ids),
        "message": {
            "message_id": 1,
            "from": user(user_id),
            "chat": {"id": user_id, "type": "private"},
            "date": 1791194400,
            "text": text,
        },
    }
    return post(update)


def press(user_id: int, data: str) -> int:
    update = {
        "update_id": next(_ids),
        "callback_query": {
            "id": f"cb{next(_ids)}",
            "from": user(user_id),
            "message": {"message_id": 2, "chat": {"id": user_id, "type": "private"}, "date": 1},
            "chat_instance": "1",
            "data": data,
        },
    }
    return post(update)


def post(update: dict[str, Any], secret: str = SECRET) -> int:
    response = Client().post(
        URL,
        data=json.dumps(update).encode(),
        content_type="application/json",
        headers={"X-Telegram-Bot-Api-Secret-Token": secret},
    )
    drain()
    return response.status_code


def demo(slug: str = "demo-toy", **changes: Any) -> dict[str, Any]:
    return demo_tenant(slug, **changes)


# ── Webhook ───────────────────────────────────────────────────────────────


def test_webhook_checks_and_stores_once(
    tenants: Any, providers: Providers, settings: Settings
) -> None:
    tenants(demo("wa"))
    update: dict[str, Any] = {
        "update_id": 5,
        "message": {
            "message_id": 1,
            "from": user(USER),
            "chat": {"id": USER, "type": "private"},
            "date": 1,
            "text": "hola",
        },
    }
    assert post(update, secret="x" * 32) == 401
    assert post(update) == 200
    assert post(update) == 200  # Telegram retried
    assert DemoEvent.objects.using("owner").count() == 1
    group = {
        **update,
        "update_id": 6,
        "message": {**update["message"], "chat": {"id": -5, "type": "group"}},
    }
    assert post(group) == 200
    assert DemoEvent.objects.using("owner").count() == 1  # groups are not even stored

    settings.DEMO_TELEGRAM_WEBHOOK_SECRET = ""
    door.cache_clear()
    assert post(update) == 404  # webhook off without its secret


def test_the_route_job_has_only_ids_and_a_hashed_lock(
    tenants: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    tenants(demo("wa"))
    monkeypatch.setattr(selector, "route_demo_event", lambda event_id: None)
    say(USER, "hola")
    (job,) = [j for j in jobs() if j[0] == "route_demo_event"]
    (event,) = DemoEvent.objects.using("owner").all()
    lock = job[1] or ""
    assert job[2] == {"event_id": str(event.id)} and lock.startswith("demo:")
    assert str(USER) not in lock


# ── Permissions and the list ───────────────────────────────────────────────


def test_a_user_without_access_is_refused(tenants: Any, providers: Providers) -> None:
    tenants(demo("wa"))
    say(STRANGER, "/start")
    assert providers.texts(STRANGER) == [selector.NO_ACCESS_TEXT]
    assert not InboundEvent.objects.using("owner").exists()


def test_a_user_without_access_is_refused_only_a_few_times(
    tenants: Any, providers: Providers
) -> None:
    tenants(demo("wa"))
    for _ in range(5):
        say(STRANGER, "hola")
    assert providers.texts(STRANGER) == [selector.NO_ACCESS_TEXT] * 3
    assert set(DemoEvent.objects.using("owner").values_list("status", flat=True)) == {"done"}


def test_an_allowed_user_sees_the_list(tenants: Any, providers: Providers) -> None:
    tenants(demo("wa"))
    say(USER, "hola")  # no business picked yet: the list
    assert providers.buttons(USER) == ["fp_select:wa", "fp_page:0"]


def test_unavailable_businesses_are_not_listed(tenants: Any, providers: Providers) -> None:
    """Unlike the retired test bot, a demo tenant with a calendar-needing pack is
    available like any other: it has its own `config.calendar_id` (§4.4). Only
    `degraded` and non-`active` (e.g. `paused`, while its setup finishes) are kept out."""
    tenants(
        demo("wa"),
        demo("bad", config={"colors": 1}),
        demo("paused", status="paused"),
    )
    say(USER, "/start")
    assert providers.buttons(USER) == ["fp_select:wa", "fp_page:0"]


def test_a_paused_business_is_not_selectable(tenants: Any, providers: Providers) -> None:
    doc = demo("paused", status="paused")
    tenants(doc)
    say(USER, "/start")
    assert providers.texts(USER) == [selector.NONE_AVAILABLE_TEXT]  # only "paused" exists
    press(USER, f"fp_select:{doc['slug']}")
    assert providers.texts(USER)[-1] == (
        f"{selector.NOT_AVAILABLE_TEXT}\n\n{selector.NONE_AVAILABLE_TEXT}"
    )


def test_the_list_is_paginated(tenants: Any, providers: Providers) -> None:
    tenants(*[demo(f"t{i:02d}") for i in range(10)])
    say(USER, "/start")
    first = providers.buttons(USER)
    assert len(first) == 10 and first[-2:] == ["fp_page:1", "fp_page:0"]
    press(USER, "fp_page:1")
    assert providers.buttons(USER) == ["fp_select:t08", "fp_select:t09", "fp_page:0"]


def test_a_real_business_never_appears(tenants: Any, providers: Providers) -> None:
    tenants(demo("wa"), wa_tenant("real"))
    say(USER, "/start")
    assert providers.buttons(USER) == ["fp_select:wa", "fp_page:0"]


# ── Picking and talking ───────────────────────────────────────────────────


def test_pick_a_business_then_talk_to_it(tenants: Any, providers: Providers) -> None:
    tenants(demo("wa"))
    say(USER, "/start")
    press(USER, "fp_select:wa")
    texts = providers.texts(USER)
    assert texts[-2] == "Demo · Wa. Escribe /negocio para cambiar."
    assert "¿Qué quieres hacer?" in texts[-1]  # the pack's menu, after the synthetic `menu`
    assert providers.buttons(USER) == ["greet", "color", "fail"]
    synthetic = InboundEvent.objects.using("owner").get(provider_event_id__startswith="select:")
    assert synthetic.channel == "demo_tg" and synthetic.status == "done"

    press(USER, "greet")  # forwarded to the tenant's demo_tg channel
    assert providers.texts(USER)[-1] == "¿Cómo te llamas?"
    contact = Contact.objects.using("owner").get()
    assert (contact.channel, contact.external_id, contact.phone_e164) == (
        "demo_tg",
        str(USER),
        None,
    )
    # The selector answered its own buttons; the pack's buttons were answered by process_event.
    acks = [
        b["callback_query_id"] for w, b in providers.telegram if w.endswith("answerCallbackQuery")
    ]
    assert len(acks) == 2


def test_negocio_shows_the_list_again(tenants: Any, providers: Providers) -> None:
    tenants(demo("wa"), demo("other"))
    say(USER, "/start")
    press(USER, "fp_select:wa")
    events = InboundEvent.objects.using("owner").count()
    say(USER, "/negocio")
    assert providers.buttons(USER) == ["fp_select:other", "fp_select:wa", "fp_page:0"]
    assert InboundEvent.objects.using("owner").count() == events  # not forwarded
    press(USER, "fp_select:other")
    assert providers.texts(USER)[-2].startswith("Demo · Other.")


def test_a_business_that_stops_being_available(
    tenants: Any, providers: Providers, tmp_path: Any
) -> None:
    doc = demo("wa")
    tenants(doc)
    say(USER, "/start")
    press(USER, "fp_select:wa")
    # A deploy breaks its config: degraded.
    import yaml

    (tmp_path / "tenants" / "wa" / "tenant.yaml").write_text(
        yaml.safe_dump({**doc, "config": {"colors": 1}})
    )
    get_registry.cache_clear()
    say(USER, "hola")
    # Merged into one message by plan_sends; no business left to list.
    assert providers.texts(USER)[-1] == (
        f"{selector.NOT_AVAILABLE_TEXT}\n\n{selector.NONE_AVAILABLE_TEXT}"
    )


def test_a_retry_of_the_same_event_does_not_repeat_the_answer(
    tenants: Any, providers: Providers
) -> None:
    tenants(demo("wa"))
    say(USER, "/start")
    (event,) = DemoEvent.objects.using("owner").all()
    before = len(providers.texts(USER))
    selector.route_demo_event(event.id)  # already done: must answer nothing more
    assert len(providers.texts(USER)) == before


# ── Isolation of the demo doors ─────────────────────────────────────────────


def test_a_demo_tenant_never_uses_a_real_channel(tenants: Any, providers: Providers) -> None:
    """Everything goes through the demo bot's own credentials, nothing through Meta,
    even a proactive message."""
    tenants(demo("wa"))
    say(USER, "/start")
    press(USER, "fp_select:wa")
    press(USER, "color")
    press(USER, "pick_1")  # replies and a SendProactive to this contact
    assert providers.meta == []
    proactive = OutboundMessage.objects.using("owner").get(kind="proactive")
    assert (proactive.channel, proactive.status) == ("demo_tg", "sent")
    assert providers.texts(USER)[-1] == "Gracias por elegir Verde. ¿Te ha gustado?"
    assert all(where.startswith("999:TEST-TOKEN/") for where, _ in providers.telegram)


def test_owner_notices_from_a_demo_tenant_reach_its_owner(
    tenants: Any, providers: Providers
) -> None:
    tenants(demo("wa", owner={"telegram_chat_id": 987654321, "notify": ["greeted"]}))
    say(USER, "/start")
    press(USER, "fp_select:wa")
    press(USER, "greet")
    say(USER, "Lucía")
    (row,) = Notification.objects.using("owner").all()
    assert (row.audience, row.text) == ("owner", "Nuevo saludo de Lucía")
    notify = [j for j in jobs() if j[0] == "send_notification"]
    assert [j[2]["notification_id"] for j in notify] == [str(row.id)]


def test_a_telegram_main_business_is_not_reachable_through_the_demo_bot(
    tenants: Any, providers: Providers
) -> None:
    """A demo tenant never uses a business's own bot (its bot_token in secrets.yaml)."""
    tenants(demo("wa"), tg_tenant("tg"))
    say(USER, "/start")
    press(USER, "fp_select:wa")
    press(USER, "color")
    press(USER, "pick_0")
    assert providers.texts(USER)[-1] == "Gracias por elegir Rojo. ¿Te ha gustado?"
    assert providers.texts(USER, token="123:ABC-token") == []
    assert all(where.startswith("999:TEST-TOKEN/") for where, _ in providers.telegram)
