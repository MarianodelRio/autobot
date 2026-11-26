"""The operator's menu in the notify bot (ADR-029), through the real webhook and
database: only the operator's chat sees it, it comes before the owner's options when
the chat also owns a business, and a long answer never breaks the common limits."""

from collections.abc import Iterator
from typing import Any

import pytest
from pytest_django import Settings

from autobot.ops.models import OpsAlert
from autobot.owner import inbox, menu, operator
from autobot.runtime.models import OwnerEvent
from core.limits import MAX_BUTTON_TITLE, MAX_ID_BYTES, MAX_INTERACTIVE_BODY, MAX_TEXT
from tests.helpers.integration import Providers, providers, wa_tenant
from tests.platform.owner.test_owner_bot import SECRET, link, post, press, say, texts

__all__ = ["providers"]  # re-exported fixture

pytestmark = [
    pytest.mark.django_db(transaction=True, databases=["default", "owner"]),
    pytest.mark.usefixtures("clean_jobs"),
]

OPS_CHAT = 777
OWNER_CHAT = 555
OPERATOR_TITLES = [o.title for o in operator.OPERATOR_MENU]
OWNER_TITLES = [o.title for o in menu.MENU]


@pytest.fixture(autouse=True)
def notify_bot(settings: Settings) -> Iterator[None]:
    settings.NOTIFY_BOT_TOKEN = "123:NOTIFY-TOKEN"
    settings.NOTIFY_BOT_WEBHOOK_SECRET = SECRET
    settings.OWNER_SUPPORT_EMAIL = "soporte@autobot.invalid"
    settings.OPS_TELEGRAM_CHAT_ID = str(OPS_CHAT)
    yield


def titles(providers: Providers) -> list[str]:
    keyboard = providers.telegram[-1][1]["reply_markup"]["inline_keyboard"]
    return [b["text"] for line in keyboard for b in line]


def test_operator_options_fit_the_common_limits() -> None:
    for option in operator.OPERATOR_MENU:
        assert option.id.startswith("ops:")
        assert len(option.id.encode()) <= MAX_ID_BYTES
        assert len(option.title) <= MAX_BUTTON_TITLE
    # With the owner's options too, the menu is still one list (at most 10 rows).
    assert len(operator.OPERATOR_MENU) + len(menu.MENU) <= 10


def test_the_operator_chat_is_recognised_by_its_configured_id(settings: Settings) -> None:
    assert operator.is_operator_chat(OPS_CHAT) and operator.is_operator_chat(" 777 ")
    assert not operator.is_operator_chat(OWNER_CHAT)
    settings.OPS_TELEGRAM_CHAT_ID = ""
    assert not operator.is_operator_chat(OPS_CHAT)


def test_the_operator_gets_its_menu_without_owning_a_business(
    tenants: Any, providers: Providers
) -> None:
    tenants(wa_tenant())
    assert post(say(OPS_CHAT, "hola")) == 200
    assert "menú de operador" in texts(providers, OPS_CHAT)[-1]
    assert titles(providers) == OPERATOR_TITLES  # not the owner's: no business here


def test_an_operator_who_owns_a_business_sees_both_menus(
    tenants: Any, providers: Providers
) -> None:
    tenants(wa_tenant(owner={"summary_monthly": False}))
    link("wa", OPS_CHAT)
    post(say(OPS_CHAT, "hola"))
    assert titles(providers) == OPERATOR_TITLES + OWNER_TITLES
    post(press(OPS_CHAT, "owner:status"))  # the owner's options still answer
    assert "Wa" in texts(providers, OPS_CHAT)[-1]


def test_other_chats_never_see_the_operator_menu(tenants: Any, providers: Providers) -> None:
    tenants(wa_tenant(owner={"summary_monthly": False}))
    link("wa", OWNER_CHAT)
    post(say(OWNER_CHAT, "hola"))
    assert titles(providers) == OWNER_TITLES
    post(press(OWNER_CHAT, "ops:status"))  # a forged payload: just the greeting again
    assert "Todo en orden" not in texts(providers, OWNER_CHAT)[-1]
    assert post(say(999, "hola")) == 200  # a stranger: the usual refusal
    assert "no está conectado" in texts(providers, 999)[-1]


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ("ops:status", "Todo en orden"),
        ("ops:alerts", "Incidencias abiertas"),
        ("ops:today", "Hoy"),
        ("ops:tenants", "Clientes"),
        ("ops:backups", "Copias y limpieza"),
    ],
)
def test_each_operator_option_answers(
    tenants: Any, providers: Providers, payload: str, expected: str
) -> None:
    tenants(wa_tenant())
    post(press(OPS_CHAT, payload))
    assert expected in texts(providers, OPS_CHAT)[-1]
    assert titles(providers) == OPERATOR_TITLES  # the menu always comes back
    assert OwnerEvent.objects.get().payload == {}  # emptied once handled


def test_a_long_answer_goes_as_a_text_and_the_menu_after_it(
    tenants: Any, providers: Providers
) -> None:
    tenants(wa_tenant())
    for i in range(20):
        OpsAlert.objects.create(kind=f"k{i}", severity="warning", text=f"🟠 alerta {i} " * 8)
    post(press(OPS_CHAT, "ops:alerts"))
    *_, answer, follow_up = texts(providers, OPS_CHAT)
    assert MAX_INTERACTIVE_BODY < len(answer) <= MAX_TEXT
    assert answer.startswith("🚨 <b>Incidencias abiertas: 20</b>")
    assert follow_up == "¿Algo más?" and titles(providers) == OPERATOR_TITLES


def test_the_operator_chat_is_not_counted_as_a_stranger(
    tenants: Any, providers: Providers, monkeypatch: pytest.MonkeyPatch
) -> None:
    tenants(wa_tenant())
    hits: list[str] = []

    def hit(key: str) -> bool:
        hits.append(key)
        return False

    monkeypatch.setattr(inbox.stranger_limiter, "hit", hit)
    post(say(OPS_CHAT, "hola"))
    assert hits == []
    post(say(999, "hola"))
    assert hits == ["all"]
