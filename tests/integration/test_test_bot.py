"""The test bot and its business selector, with the toy
pack, the real database and Telegram/Meta answered by a mock transport. Covers who may
use it (operators only; the per-business testers list was retired with testers.telegram
and the demo doors of channels/demo/), picking and switching businesses, businesses that
stop being available and the isolation of the test channel: never the main channel, and
its owner notices go to ops. A pack that needs a calendar is never available here (the
test channel has none of its own anymore)."""

import dataclasses
import json
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from django.test import Client
from pydantic import BaseModel
from pytest_django import Settings

from flowpilot.channels import adapters
from flowpilot.channels.ratelimit import WindowLimiter
from flowpilot.channels.test_bot import selector
from flowpilot.runtime import outbound, process
from flowpilot.runtime.models import (
    Contact,
    InboundEvent,
    Notification,
    OutboundMessage,
    TestBotEvent,
    TestSession,
)
from flowpilot.tenancy.registry import get_registry
from tests.integration.helpers import jobs, tg_tenant, wa_tenant
from tests.toy_pack import pack as toy

pytestmark = [
    pytest.mark.django_db(transaction=True, databases=["default", "owner"]),
    pytest.mark.usefixtures("clean_jobs"),
]

OPERATOR = 1
TESTER = 111  # an arbitrary non-operator id, used only where access is not exercised
STRANGER = 222
SECRET = "t" * 32
URL = "/webhooks/telegram-test"
_ids = iter(range(900_000_001, 999_999_999))


@pytest.fixture(autouse=True)
def test_bot(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(selector, "refusals", WindowLimiter(limit=3, window_s=3600))
    settings.TEST_BOT_TOKEN = "999:TEST-TOKEN"
    settings.TEST_BOT_WEBHOOK_SECRET = SECRET
    settings.TEST_BOT_OPERATORS = frozenset({OPERATOR})
    adapters.test_bot_secrets.cache_clear()
    yield
    adapters.test_bot_secrets.cache_clear()


class Providers:
    """What was sent to Telegram (per bot token) and to Meta."""

    def __init__(self) -> None:
        self.telegram: list[tuple[str, dict[str, Any]]] = []
        self.meta: list[httpx.Request] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        if request.url.host == "graph.facebook.com":
            self.meta.append(request)
            return httpx.Response(200, json={"messages": [{"id": "wamid.X"}]})
        token, method = request.url.path.removeprefix("/bot").split("/")
        body = json.loads(request.content)
        self.telegram.append((f"{token}/{method}", body))
        return httpx.Response(200, json={"ok": True, "result": {"message_id": len(self.telegram)}})

    def texts(self, chat: int, token: str = "999:TEST-TOKEN") -> list[str]:
        return [
            body["text"]
            for where, body in self.telegram
            if where == f"{token}/sendMessage" and body["chat_id"] == str(chat)
        ]

    def buttons(self, chat: int) -> list[str]:
        sent = [
            b for w, b in self.telegram if w.endswith("sendMessage") and b["chat_id"] == str(chat)
        ]
        keyboard = sent[-1].get("reply_markup", {}).get("inline_keyboard", [])
        return [line[0]["callback_data"] for line in keyboard]


@pytest.fixture
def providers(monkeypatch: pytest.MonkeyPatch) -> Providers:
    found = Providers()
    client = httpx.Client(transport=httpx.MockTransport(found.handler))
    monkeypatch.setattr(adapters.TELEGRAM, "client", client)
    monkeypatch.setattr(adapters.WHATSAPP, "client", client)
    return found


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


def drain(**process_kwargs: Any) -> None:
    """Run what the worker would: route, process and send, in order."""
    for event in (
        TestBotEvent.objects.using("owner").filter(status="pending").order_by("received_at")
    ):
        selector.route_test_update(event.id)
    for inbound in (
        InboundEvent.objects.using("owner").filter(status="pending").order_by("received_at")
    ):
        process.process_event(inbound.tenant_id, inbound.id, last_attempt=False, **process_kwargs)
    for message in (
        OutboundMessage.objects.using("owner")
        .filter(status="pending")
        .order_by("created_at", "seq")
    ):
        outbound.send_message(message.tenant_id, message.id)


def wa_t(slug: str, **changes: Any) -> dict[str, Any]:
    return wa_tenant(slug, **changes)


# ── Webhook ───────────────────────────────────────────────────────────────


def test_webhook_checks_and_stores_once(
    tenants: Any, providers: Providers, settings: Settings
) -> None:
    tenants(wa_t("wa"))
    update: dict[str, Any] = {
        "update_id": 5,
        "message": {
            "message_id": 1,
            "from": user(TESTER),
            "chat": {"id": TESTER, "type": "private"},
            "date": 1,
            "text": "hola",
        },
    }
    assert post(update, secret="x" * 32) == 401
    assert post(update) == 200
    assert post(update) == 200  # Telegram retried
    assert TestBotEvent.objects.using("owner").count() == 1
    group = {
        **update,
        "update_id": 6,
        "message": {**update["message"], "chat": {"id": -5, "type": "group"}},
    }
    assert post(group) == 200
    assert TestBotEvent.objects.using("owner").count() == 1  # groups are not even stored

    settings.TEST_BOT_WEBHOOK_SECRET = ""
    assert post(update) == 404  # webhook off without its secret


def test_the_route_job_has_only_ids_and_a_hashed_lock(
    tenants: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    tenants(wa_t("wa"))
    monkeypatch.setattr(selector, "route_test_update", lambda event_id: None)
    say(TESTER, "hola")
    (job,) = [j for j in jobs() if j[0] == "route_test_update"]
    (event,) = TestBotEvent.objects.using("owner").all()
    lock = job[1] or ""
    assert job[2] == {"event_id": str(event.id)} and lock.startswith("tg:")
    assert str(TESTER) not in lock


# ── Permissions and the list ──────────────────────────────────────────────


def test_a_user_without_permission_is_refused(tenants: Any, providers: Providers) -> None:
    tenants(wa_t("wa"))
    say(STRANGER, "/start")
    assert providers.texts(STRANGER) == [selector.NO_ACCESS_TEXT]
    assert not InboundEvent.objects.using("owner").exists()
    assert not TestSession.objects.using("owner").exists()


def test_a_user_without_permission_is_refused_only_a_few_times(
    tenants: Any, providers: Providers
) -> None:
    tenants(wa_t("wa"))
    for _ in range(5):
        say(STRANGER, "hola")
    assert providers.texts(STRANGER) == [selector.NO_ACCESS_TEXT] * 3
    assert set(TestBotEvent.objects.using("owner").values_list("status", flat=True)) == {"done"}


def test_only_operators_see_the_list(tenants: Any, providers: Providers) -> None:
    tenants(wa_t("wa"))
    say(OPERATOR, "hola")  # no business picked yet: the list
    assert providers.buttons(OPERATOR) == ["fp_select:wa", "fp_page:0"]


def test_unavailable_businesses_are_not_listed(
    tenants: Any, providers: Providers, monkeypatch: pytest.MonkeyPatch
) -> None:
    class CalendarConfig(BaseModel):
        calendar_id: str = "real@example.com"

    calendar_pack = dataclasses.replace(
        toy.pack, name="cal", needs_calendar=True, config_schema=CalendarConfig
    )
    monkeypatch.setattr("packs.registry.PACKS", {"toy": toy.pack, "cal": calendar_pack})
    tenants(
        wa_t("wa"),
        wa_t("off", status="offboarded"),
        wa_t("bad", config={"colors": 1}),
        wa_t("nocal", pack="cal"),
        wa_t("paused", status="paused"),
    )
    say(OPERATOR, "/start")
    assert providers.buttons(OPERATOR) == ["fp_select:paused", "fp_select:wa", "fp_page:0"]


def test_the_list_is_paginated(tenants: Any, providers: Providers) -> None:
    tenants(*[wa_t(f"t{i:02d}") for i in range(10)])
    say(OPERATOR, "/start")
    first = providers.buttons(OPERATOR)
    assert len(first) == 10 and first[-2:] == ["fp_page:1", "fp_page:0"]
    press(OPERATOR, "fp_page:1")
    assert providers.buttons(OPERATOR) == ["fp_select:t08", "fp_select:t09", "fp_page:0"]


# ── Picking and talking ───────────────────────────────────────────────────


def test_pick_a_business_then_talk_to_it(tenants: Any, providers: Providers) -> None:
    tenants(wa_t("wa"))
    say(OPERATOR, "/start")
    press(OPERATOR, "fp_select:wa")
    texts = providers.texts(OPERATOR)
    assert texts[-2] == "🧪 Pruebas · Wa. Escribe /negocio para cambiar."
    assert "¿Qué quieres hacer?" in texts[-1]  # the pack's menu, after the synthetic `menu`
    assert providers.buttons(OPERATOR) == ["greet", "color", "fail"]
    tenant = get_registry().by_slug["wa"]
    assert TestSession.objects.using("owner").get(telegram_user_id=OPERATOR).tenant_id == tenant.id
    synthetic = InboundEvent.objects.using("owner").get(provider_event_id__startswith="select:")
    assert synthetic.channel == "test" and synthetic.status == "done"

    press(OPERATOR, "greet")  # forwarded to the tenant's test channel
    assert providers.texts(OPERATOR)[-1] == "¿Cómo te llamas?"
    contact = Contact.objects.using("owner").get()
    assert (contact.channel, contact.external_id, contact.phone_e164) == (
        "test",
        str(OPERATOR),
        None,
    )
    # The selector answered its own buttons; the pack's buttons were answered by process_event.
    acks = [
        b["callback_query_id"] for w, b in providers.telegram if w.endswith("answerCallbackQuery")
    ]
    assert len(acks) == 2


def test_negocio_shows_the_list_again(tenants: Any, providers: Providers) -> None:
    tenants(wa_t("wa"), wa_t("other"))
    say(OPERATOR, "/start")
    press(OPERATOR, "fp_select:wa")
    events = InboundEvent.objects.using("owner").count()
    say(OPERATOR, "/negocio")
    assert providers.buttons(OPERATOR) == ["fp_select:other", "fp_select:wa", "fp_page:0"]
    assert InboundEvent.objects.using("owner").count() == events  # not forwarded
    press(OPERATOR, "fp_select:other")
    assert providers.texts(OPERATOR)[-2].startswith("🧪 Pruebas · Other.")


def test_a_business_that_stops_being_available(
    tenants: Any, providers: Providers, tmp_path: Any
) -> None:
    doc = wa_t("wa")
    tenants(doc)
    say(OPERATOR, "/start")
    press(OPERATOR, "fp_select:wa")
    # A deploy breaks its config: degraded.
    import yaml

    (tmp_path / "tenants" / "wa" / "tenant.yaml").write_text(
        yaml.safe_dump({**doc, "config": {"colors": 1}})
    )
    get_registry.cache_clear()
    say(OPERATOR, "hola")
    # Merged into one message by plan_sends; no business left to list.
    assert providers.texts(OPERATOR)[-1] == (
        f"{selector.NOT_AVAILABLE_TEXT}\n\n{selector.NONE_AVAILABLE_TEXT}"
    )
    assert not TestSession.objects.using("owner").exists()


# ── Isolation of the test channel ─────────────────────────────────────────


def test_the_test_channel_never_uses_the_main_channel(tenants: Any, providers: Providers) -> None:
    """A WhatsApp business tested through the test bot: everything goes through the test
    bot, nothing through Meta, even a proactive message."""
    tenants(wa_t("wa"))
    say(OPERATOR, "/start")
    press(OPERATOR, "fp_select:wa")
    press(OPERATOR, "color")
    press(OPERATOR, "pick_1")  # replies and a SendProactive to this contact
    assert providers.meta == []
    proactive = OutboundMessage.objects.using("owner").get(kind="proactive")
    assert (proactive.channel, proactive.status) == ("test", "sent")
    assert providers.texts(OPERATOR)[-1] == "Gracias por elegir Verde. ¿Te ha gustado?"
    assert all(where.startswith("999:TEST-TOKEN/") for where, _ in providers.telegram)


@pytest.mark.parametrize(
    "owner", [{"telegram_chat_id": 987654321, "notify": ["greeted"]}, None], ids=["owner", "none"]
)
def test_owner_notices_from_the_test_channel_go_to_ops(
    tenants: Any, providers: Providers, owner: dict[str, Any] | None
) -> None:
    """Always to ops, never to the owner: also when the owner has no chat."""
    tenants(wa_t("wa", owner=owner))
    say(OPERATOR, "/start")
    press(OPERATOR, "fp_select:wa")
    press(OPERATOR, "greet")
    say(OPERATOR, "Lucía")
    (row,) = Notification.objects.using("owner").all()
    assert (row.audience, row.text) == ("ops", "🧪 Wa: Nuevo saludo de Lucía")
    notify = [j for j in jobs() if j[0] == "send_notification"]
    assert [j[2]["notification_id"] for j in notify] == [str(row.id)]


def test_a_telegram_business_is_tested_through_the_test_bot_only(
    tenants: Any, providers: Providers
) -> None:
    """Never through the business's own bot (its bot_token in secrets.yaml)."""
    tenants(tg_tenant("tg"))
    say(OPERATOR, "/start")
    press(OPERATOR, "fp_select:tg")
    press(OPERATOR, "color")
    press(OPERATOR, "pick_0")
    assert providers.texts(OPERATOR)[-1] == "Gracias por elegir Rojo. ¿Te ha gustado?"
    assert providers.texts(OPERATOR, token="123:ABC-token") == []
    assert all(where.startswith("999:TEST-TOKEN/") for where, _ in providers.telegram)
