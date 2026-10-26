"""`telegram_poll` and `telegram_set_webhook`, with the Bot
API answered by a mock transport."""

import io
import json
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from django.core.management import CommandError, call_command
from pytest_django import Settings

from flowpilot.channels import views
from flowpilot.channels.demo.doors import door
from flowpilot.channels.telegram import polling
from flowpilot.runtime.models import Channel, DemoEvent, InboundEvent
from tests.integration.helpers import jobs, tg_tenant
from tests.tenancy.helpers import TG_SECRETS

REAL_CLIENT = httpx.Client  # the commands' httpx.Client is patched to build these

pytestmark = [
    pytest.mark.django_db(transaction=True, databases=["default", "owner"]),
    pytest.mark.usefixtures("clean_jobs"),
]


@pytest.fixture(autouse=True)
def demo_bot(settings: Settings) -> Iterator[None]:
    settings.DEMO_TELEGRAM_TOKEN = "999:TEST-TOKEN"
    settings.DEMO_TELEGRAM_WEBHOOK_SECRET = "t" * 32
    settings.DEMO_TELEGRAM_USERS = frozenset({1})
    settings.PUBLIC_URL = "https://api.example.org/"
    door.cache_clear()
    yield
    door.cache_clear()


class BotApi:
    """Answers each Bot API call with the next answer, and records the calls."""

    def __init__(self, *answers: httpx.Response | Exception) -> None:
        self.answers = list(answers)
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.client = self.new_client()

    def new_client(self) -> httpx.Client:
        return REAL_CLIENT(transport=httpx.MockTransport(self.handle))

    def handle(self, request: httpx.Request) -> httpx.Response:
        token, method = request.url.path.removeprefix("/bot").split("/")
        self.calls.append((f"{token}/{method}", json.loads(request.content or b"{}")))
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    def stop_when_done(self) -> bool:
        return not self.answers


def updates(*items: dict[str, Any]) -> httpx.Response:
    return httpx.Response(200, json={"ok": True, "result": list(items)})


def message(update_id: int, user_id: int = 1, text: str = "hola") -> dict[str, Any]:
    sender = {"id": user_id, "is_bot": False, "first_name": "Op"}
    return {
        "update_id": update_id,
        "message": {
            "message_id": 1,
            "from": sender,
            "chat": {"id": user_id, "type": "private"},
            "date": 1791194400,
            "text": text,
        },
    }


# ── telegram_poll enters the same way as the webhook ──────────────────────


def test_the_demo_bot_source_stores_through_the_selector() -> None:
    bot = polling.source(None)
    assert bot.name == "demo bot"
    bot.accept(message(1))
    assert DemoEvent.objects.using("owner").filter(channel=Channel.DEMO_TG).count() == 1


def test_a_tenant_bot_source_goes_through_the_webhook_entry(
    tenants: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    tenants(tg_tenant())
    seen: list[str] = []
    monkeypatch.setattr(views, "accept", lambda tenant, body, parse: seen.append(tenant.slug))
    bot = polling.source("tg")
    assert bot.secrets.bot_token.get_secret_value() == TG_SECRETS["bot_token"]
    bot.accept(message(1))
    assert seen == ["tg"]


def test_polling_the_demo_bot_stores_and_queues_like_the_webhook(tenants: Any) -> None:
    tenants(tg_tenant())
    api = BotApi(updates(message(10), message(11)))
    polling.poll(polling.source(None), api.client, stop=lambda: not api.answers)
    assert sorted(DemoEvent.objects.using("owner").values_list("provider_event_id", flat=True)) == [
        "10",
        "11",
    ]
    assert [j[0] for j in jobs()] == ["route_demo_event", "route_demo_event"]
    ((where, params),) = api.calls
    assert where == "999:TEST-TOKEN/getUpdates"
    assert params == {"timeout": 25, "allowed_updates": ["message", "callback_query"]}


def test_polling_a_tenant_bot_stores_like_its_webhook(tenants: Any) -> None:
    tenants(tg_tenant())
    api = BotApi(updates(message(20, user_id=100000001)))
    polling.poll(polling.source("tg"), api.client, stop=lambda: not api.answers)
    (event,) = InboundEvent.objects.using("owner").all()
    assert (event.channel, event.provider_event_id, event.status) == ("main", "20", "pending")
    assert api.calls[0][0] == f"{TG_SECRETS['bot_token']}/getUpdates"


def test_the_offset_moves_on_and_errors_do_not_stop_polling(
    tenants: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    tenants(tg_tenant())
    calls: list[int] = []

    def flaky(update: dict[str, Any]) -> bool:
        calls.append(update["update_id"])
        if update["update_id"] == 30:
            raise RuntimeError("bug")
        return True

    bot = polling.Source("demo bot", polling.source(None).secrets, flaky)
    pauses: list[float] = []
    api = BotApi(
        httpx.Response(502),
        httpx.ConnectError("down"),
        updates(message(30), message(31)),
        updates(),
    )
    polling.poll(bot, api.client, stop=lambda: not api.answers, sleep=pauses.append)
    assert pauses == [3.0, 3.0] and calls == [30, 31]
    assert api.calls[-1][1]["offset"] == 32


def test_a_tenant_bot_is_polled_only_if_its_webhook_would_accept_it(tenants: Any) -> None:
    disabled = tg_tenant("tg")
    del disabled["channel"]["bot_username"]  # main channel not set up yet
    twin = tg_tenant("twin")
    twin["channel"]["public_id"] = "pubtwin00"
    copy = tg_tenant("copy")
    copy["channel"]["public_id"] = "pubtwin00"  # ambiguous
    tenants(disabled, twin, copy)
    for slug in ("tg", "twin", "copy"):
        with pytest.raises(ValueError, match="no enabled Telegram main channel"):
            polling.source(slug)
    with pytest.raises(CommandError, match="no enabled Telegram main channel"):
        call_command("telegram_poll", "tg", stdout=io.StringIO())


def test_polling_stops_on_an_invalid_token(monkeypatch: pytest.MonkeyPatch) -> None:
    api = BotApi(httpx.Response(401, json={"ok": False, "error_code": 401}))
    monkeypatch.setattr("httpx.Client", lambda **kwargs: api.new_client())
    with pytest.raises(CommandError, match="refuses the token of demo bot"):
        call_command("telegram_poll", stdout=io.StringIO())


def test_polling_refuses_a_bot_with_a_webhook() -> None:
    api = BotApi(httpx.Response(409, json={"ok": False, "error_code": 409}))
    with pytest.raises(polling.WebhookActive):
        polling.poll(polling.source(None), api.client)


def test_poll_command_explains_how_to_remove_the_webhook(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = BotApi(httpx.Response(409, json={"ok": False, "error_code": 409}))
    monkeypatch.setattr("httpx.Client", lambda **kwargs: api.new_client())
    with pytest.raises(CommandError, match="telegram_set_webhook demo --delete"):
        call_command("telegram_poll", stdout=io.StringIO())


def test_poll_command_needs_the_demo_telegram_token(settings: Settings) -> None:
    settings.DEMO_TELEGRAM_TOKEN = ""
    door.cache_clear()
    with pytest.raises(CommandError, match="DEMO_TELEGRAM_TOKEN"):
        call_command("telegram_poll", stdout=io.StringIO())


# ── telegram_set_webhook ──────────────────────────────────────────────────


def set_webhook(api: BotApi, monkeypatch: pytest.MonkeyPatch, *args: str) -> str:
    monkeypatch.setattr("httpx.Client", lambda **kwargs: api.new_client())
    out = io.StringIO()
    call_command("telegram_set_webhook", *args, stdout=out)
    return out.getvalue()


def test_set_the_demo_bot_webhook(monkeypatch: pytest.MonkeyPatch) -> None:
    api = BotApi(httpx.Response(200, json={"ok": True, "result": True}))
    out = set_webhook(api, monkeypatch, "demo")
    ((where, params),) = api.calls
    assert where == "999:TEST-TOKEN/setWebhook"
    assert params == {
        "url": "https://api.example.org/webhooks/telegram-demo",
        "secret_token": "t" * 32,
        "allowed_updates": ["message", "callback_query"],
    }
    assert "TEST-TOKEN" not in out and "t" * 32 not in out


def test_set_a_tenant_bot_webhook(tenants: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    tenants(tg_tenant())
    api = BotApi(httpx.Response(200, json={"ok": True, "result": True}))
    set_webhook(api, monkeypatch, "tg")
    ((where, params),) = api.calls
    assert where == f"{TG_SECRETS['bot_token']}/setWebhook"
    assert params["url"] == "https://api.example.org/webhooks/telegram/pubtg0000"
    assert params["secret_token"] == TG_SECRETS["webhook_secret"]


def test_delete_a_webhook(monkeypatch: pytest.MonkeyPatch) -> None:
    api = BotApi(httpx.Response(200, json={"ok": True, "result": True}))
    assert "deleted" in set_webhook(api, monkeypatch, "demo", "--delete")
    assert api.calls[0][0] == "999:TEST-TOKEN/deleteWebhook"


def test_set_webhook_errors(
    tenants: Any, monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    tenants(tg_tenant())
    api = BotApi(httpx.Response(401, json={"ok": False, "error_code": 401}))
    with pytest.raises(CommandError, match="Telegram refused it: HTTP 401, error 401"):
        set_webhook(api, monkeypatch, "demo")
    with pytest.raises(CommandError, match="no tenant"):
        set_webhook(api, monkeypatch, "nobody")
    settings.PUBLIC_URL = ""
    with pytest.raises(CommandError, match="PUBLIC_URL"):
        set_webhook(api, monkeypatch, "tg")
    settings.PUBLIC_URL = "https://api.example.org"
    settings.DEMO_TELEGRAM_WEBHOOK_SECRET = ""
    with pytest.raises(CommandError, match="DEMO_TELEGRAM_WEBHOOK_SECRET"):
        set_webhook(api, monkeypatch, "demo")
