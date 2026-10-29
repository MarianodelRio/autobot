"""The owner bot's conversation scenario: webhook authenticity, linking by invite
code, the menu and its two options, and the common limits
(`docs/mejoras/02-avisos-y-resumenes.md` §6, §9). Telegram is simulated as in
`test_notifications.py`, through the real webhook and the real database."""

import hashlib
import io
import json
import re
from collections.abc import Iterator
from decimal import Decimal
from typing import Any

import httpx
import pytest
from django.core.management import CommandError, call_command
from django.test import Client
from django.utils import timezone
from pytest_django import Settings

from autobot.owner import inbox, links, menu
from autobot.runtime.models import MetricEvent, OwnerEvent, OwnerLink
from autobot.tenancy.registry import get_registry
from core.limits import MAX_BUTTON_TITLE, MAX_ID_BYTES
from tests.integration.helpers import Providers, demo_tenant, providers, wa_tenant

__all__ = ["providers"]  # re-exported fixture

pytestmark = [
    pytest.mark.django_db(transaction=True, databases=["default", "owner"]),
    pytest.mark.usefixtures("clean_jobs"),
]

REAL_CLIENT = httpx.Client  # the commands' httpx.Client is patched to build these
URL = "/webhooks/telegram-notify"
SECRET = "n" * 32
OWNER_CHAT = 555
_ids = iter(range(1, 10_000_000))


@pytest.fixture(autouse=True)
def notify_bot(settings: Settings) -> Iterator[None]:
    settings.NOTIFY_BOT_TOKEN = "123:NOTIFY-TOKEN"
    settings.NOTIFY_BOT_WEBHOOK_SECRET = SECRET
    settings.OWNER_SUPPORT_EMAIL = "soporte@autobot.invalid"
    yield


def user(user_id: int) -> dict[str, Any]:
    return {"id": user_id, "is_bot": False, "first_name": "Dueña"}


def say(chat_id: int, text: str) -> dict[str, Any]:
    return {
        "update_id": next(_ids),
        "message": {
            "message_id": 1,
            "from": user(chat_id),
            "chat": {"id": chat_id, "type": "private"},
            "date": 1791194400,
            "text": text,
        },
    }


def press(chat_id: int, data: str) -> dict[str, Any]:
    return {
        "update_id": next(_ids),
        "callback_query": {
            "id": f"cb{next(_ids)}",
            "from": user(chat_id),
            "message": {"message_id": 2, "chat": {"id": chat_id, "type": "private"}, "date": 1},
            "chat_instance": "1",
            "data": data,
        },
    }


def post(update: dict[str, Any], secret: str | None = SECRET) -> int:
    headers = {} if secret is None else {"X-Telegram-Bot-Api-Secret-Token": secret}
    response = Client().post(
        URL, data=json.dumps(update).encode(), content_type="application/json", headers=headers
    )
    drain_owner()
    return response.status_code


def drain_owner() -> None:
    for event in OwnerEvent.objects.filter(status="pending").order_by("received_at"):
        inbox.handle_owner_event(event.id)


def texts(providers: Providers, chat_id: int = OWNER_CHAT) -> list[str]:
    return providers.texts(chat_id, token="123:NOTIFY-TOKEN")


def link(slug: str, chat_id: int = OWNER_CHAT) -> None:
    tenant = get_registry().by_slug[slug]
    OwnerLink.objects.create(tenant_id=tenant.id, chat_id=chat_id, linked_at=timezone.now())


def invite(slug: str) -> str:
    tenant = get_registry().by_slug[slug]
    return links.new_invite(tenant.id)


def metric(slug: str, value: int) -> None:
    tenant = get_registry().by_slug[slug]
    MetricEvent.objects.using("owner").create(
        tenant_id=tenant.id, idem_key="g1", kind="greeted", value=Decimal(value)
    )


def _button_titles(providers: Providers) -> list[str]:
    buttons = providers.telegram[-1][1]["reply_markup"]["inline_keyboard"]
    return [b["text"] for row in buttons for b in row]


# ── Menu declaration ────────────────────────────────────────────────────────


def test_menu_options_fit_the_common_limits() -> None:
    for option in menu.MENU:
        assert len(option.id.encode()) <= MAX_ID_BYTES
        assert len(option.title) <= MAX_BUTTON_TITLE


# ── Webhook ──────────────────────────────────────────────────────────────


def test_webhook_requires_the_secret(tenants: Any, providers: Providers) -> None:
    tenants(wa_tenant(owner={"summary_monthly": False}))
    link("wa")
    update = say(OWNER_CHAT, "hola")
    assert post(update, secret=None) == 401  # no header: Telegram never sends an empty one
    assert post(update, secret="x" * 32) == 401
    assert post(update) == 200


def test_webhook_404_without_configuration(settings: Settings) -> None:
    settings.NOTIFY_BOT_WEBHOOK_SECRET = ""
    assert post(say(OWNER_CHAT, "hola")) == 404


def test_duplicate_update_is_stored_once(tenants: Any, providers: Providers) -> None:
    tenants(wa_tenant())
    link("wa")
    update = say(OWNER_CHAT, "hola")
    assert post(update) == 200
    assert post(update) == 200  # Telegram retried
    assert OwnerEvent.objects.count() == 1


# ── Linking ──────────────────────────────────────────────────────────────


def test_start_with_a_valid_code_links_and_shows_the_menu(
    tenants: Any, providers: Providers
) -> None:
    tenants(wa_tenant())
    code = invite("wa")
    assert post(say(OWNER_CHAT, f"/start {code}")) == 200
    assert OwnerLink.objects.get(tenant_id=get_registry().by_slug["wa"].id).chat_id == OWNER_CHAT
    sent = texts(providers)
    assert "conectado" in sent[-1] and "Wa" in sent[-1]
    assert _button_titles(providers) == [o.title for o in menu.MENU]


def test_start_with_an_unknown_or_expired_code_is_invalid(
    tenants: Any, providers: Providers
) -> None:
    tenants(wa_tenant())
    assert post(say(OWNER_CHAT, "/start nosuchcode")) == 200
    assert "válido" in texts(providers)[-1]
    assert not OwnerLink.objects.filter(chat_id=OWNER_CHAT).exists()


def test_start_code_is_single_use(tenants: Any, providers: Providers) -> None:
    tenants(wa_tenant())
    code = invite("wa")
    post(say(OWNER_CHAT, f"/start {code}"))
    other_chat = OWNER_CHAT + 1
    assert post(say(other_chat, f"/start {code}")) == 200
    assert "válido" in texts(providers, other_chat)[-1]
    assert OwnerLink.objects.get(tenant_id=get_registry().by_slug["wa"].id).chat_id == OWNER_CHAT


def test_chat_taken_by_another_real_tenant_leaves_the_code_intact(
    tenants: Any, providers: Providers
) -> None:
    tenants(wa_tenant("a"), wa_tenant("b"))
    link("a", OWNER_CHAT)
    code = invite("b")
    digest = hashlib.sha256(code.encode()).hexdigest()
    assert post(say(OWNER_CHAT, f"/start {code}")) == 200
    assert "conectado con otro negocio" in texts(providers)[-1]
    link_b = OwnerLink.objects.get(tenant_id=get_registry().by_slug["b"].id)
    assert link_b.chat_id is None and link_b.invite_hash == digest


def test_chat_taken_without_support_email_names_no_empty_address(
    tenants: Any, providers: Providers, settings: Settings
) -> None:
    settings.OWNER_SUPPORT_EMAIL = ""
    tenants(wa_tenant("a"), wa_tenant("b"))
    link("a", OWNER_CHAT)
    assert post(say(OWNER_CHAT, f"/start {invite('b')}")) == 200
    text = texts(providers)[-1]
    assert "conectado con otro negocio" in text
    assert "escribe a ." not in text and "quien te dio de alta" in text


def test_two_demo_tenants_can_share_the_same_chat(tenants: Any, providers: Providers) -> None:
    tenants(demo_tenant("demo-a"), demo_tenant("demo-b"))
    link("demo-a", OWNER_CHAT)
    code = invite("demo-b")
    assert post(say(OWNER_CHAT, f"/start {code}")) == 200
    assert OwnerLink.objects.get(tenant_id=get_registry().by_slug["demo-b"].id).chat_id == (
        OWNER_CHAT
    )
    assert "conectado" in texts(providers)[-1]


# ── Menu and its options ──────────────────────────────────────────────────


def test_free_text_from_a_linked_chat_shows_the_greeting_with_buttons(
    tenants: Any, providers: Providers
) -> None:
    tenants(wa_tenant())
    link("wa")
    assert post(say(OWNER_CHAT, "buenas")) == 200
    assert "Wa" in providers.telegram[-1][1]["text"]
    assert _button_titles(providers) == [o.title for o in menu.MENU]


def test_owner_status_shows_the_pack_line_for_the_current_month(
    tenants: Any, providers: Providers
) -> None:
    tenants(wa_tenant())
    link("wa")
    metric("wa", 3)
    assert post(press(OWNER_CHAT, "owner:status")) == 200
    text = texts(providers)[-1]
    assert "Así va" in text and "Saludos: 3" in text


def test_owner_contact_shows_the_support_email(tenants: Any, providers: Providers) -> None:
    tenants(wa_tenant())
    link("wa")
    assert post(press(OWNER_CHAT, "owner:contact")) == 200
    assert "soporte@autobot.invalid" in texts(providers)[-1]


def test_without_support_email_the_menu_has_only_one_button(
    tenants: Any, providers: Providers, settings: Settings
) -> None:
    settings.OWNER_SUPPORT_EMAIL = ""
    tenants(wa_tenant())
    link("wa")
    assert post(say(OWNER_CHAT, "hola")) == 200
    assert _button_titles(providers) == ["📊 Cómo va el mes"]


# ── Not linked ─────────────────────────────────────────────────────────────


def test_not_linked_chat_is_refused_then_silenced_after_three(
    tenants: Any, providers: Providers
) -> None:
    tenants(wa_tenant())
    for _ in range(3):
        assert post(say(OWNER_CHAT, "hola")) == 200
    assert len(texts(providers)) == 3
    assert all("conectado a ningún negocio" in t for t in texts(providers))
    assert post(say(OWNER_CHAT, "hola")) == 200  # the 4th: silence
    assert len(texts(providers)) == 3


# ── Status of a tenant that is not usable ──────────────────────────────────


def test_a_paused_real_tenant_shows_not_active(tenants: Any, providers: Providers) -> None:
    tenants(wa_tenant(status="paused"))
    link("wa")
    assert post(press(OWNER_CHAT, "owner:status")) == 200
    assert "todavía no está activo" in texts(providers)[-1]


def test_a_paused_demo_tenant_still_shows_its_figures(tenants: Any, providers: Providers) -> None:
    tenants(demo_tenant("demo-a", status="paused"))
    link("demo-a", OWNER_CHAT)
    metric("demo-a", 5)
    assert post(press(OWNER_CHAT, "owner:status")) == 200
    assert "Saludos: 5" in texts(providers)[-1]


def test_a_chat_shared_by_two_demo_tenants_gets_one_block_each(
    tenants: Any, providers: Providers
) -> None:
    tenants(demo_tenant("demo-a"), demo_tenant("demo-b"))
    link("demo-a", OWNER_CHAT)
    link("demo-b", OWNER_CHAT)
    metric("demo-a", 2)
    assert post(press(OWNER_CHAT, "owner:status")) == 200
    text = texts(providers)[-1]
    assert text.count("Así va") == 1
    assert text.count("Saludos:") == 2 and "Saludos: 2" in text


# ── Operation commands ─────────────────────────────────────────────────────


def get_me() -> httpx.Response:
    return httpx.Response(200, json={"ok": True, "result": {"username": "AvisosBot"}})


def run(command: str, *args: str, monkeypatch: pytest.MonkeyPatch, answer: Any = None) -> str:
    transport = httpx.MockTransport(lambda request: answer or get_me())
    monkeypatch.setattr("httpx.Client", lambda **kwargs: REAL_CLIENT(transport=transport))
    out = io.StringIO()
    call_command(command, *args, stdout=out)
    return out.getvalue()


def test_owner_invite_prints_a_link_that_links_the_chat(
    tenants: Any, providers: Providers, monkeypatch: pytest.MonkeyPatch
) -> None:
    tenants(wa_tenant())
    out = run("owner_invite", "wa", monkeypatch=monkeypatch)
    match = re.search(r"https://t\.me/AvisosBot\?start=([A-Za-z0-9_-]+)", out)
    assert match is not None and "Ya hay un chat" not in out
    assert post(say(OWNER_CHAT, f"/start {match[1]}")) == 200
    assert links.owner_chat(get_registry().by_slug["wa"].id) == OWNER_CHAT


def test_owner_invite_replaces_the_pending_code_and_warns_if_linked(
    tenants: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    tenants(wa_tenant())
    first = invite("wa")
    link_row = OwnerLink.objects.get(tenant_id=get_registry().by_slug["wa"].id)
    OwnerLink.objects.filter(id=link_row.id).update(chat_id=OWNER_CHAT)
    out = run("owner_invite", "wa", monkeypatch=monkeypatch)
    assert "Ya hay un chat conectado" in out
    assert first not in out
    assert OwnerLink.objects.get(id=link_row.id).invite_hash != (
        hashlib.sha256(first.encode()).hexdigest()
    )


def test_owner_invite_errors(
    tenants: Any, monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    tenants(wa_tenant(), wa_tenant("gone", status="offboarded"))
    with pytest.raises(CommandError, match="Negocio desconocido"):
        run("owner_invite", "nobody", monkeypatch=monkeypatch)
    with pytest.raises(CommandError, match="dado de baja"):
        run("owner_invite", "gone", monkeypatch=monkeypatch)
    refused = httpx.Response(401, json={"ok": False, "error_code": 401})
    with pytest.raises(CommandError, match="Telegram rechazó"):
        run("owner_invite", "wa", monkeypatch=monkeypatch, answer=refused)
    settings.NOTIFY_BOT_TOKEN = ""
    with pytest.raises(CommandError, match="NOTIFY_BOT_TOKEN"):
        run("owner_invite", "wa", monkeypatch=monkeypatch)
    assert not OwnerLink.objects.exists()  # no failed run leaves an invite behind


def test_owner_unlink_clears_the_chat_and_any_pending_invite(
    tenants: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    tenants(wa_tenant())
    wa = get_registry().by_slug["wa"]
    assert "no tenía ningún chat" in run("owner_unlink", "wa", monkeypatch=monkeypatch)
    link("wa")
    OwnerLink.objects.filter(tenant_id=wa.id).update(invite_hash="x" * 64)
    assert "desconectado" in run("owner_unlink", "wa", monkeypatch=monkeypatch)
    row = OwnerLink.objects.get(tenant_id=wa.id)
    assert (row.chat_id, row.linked_at, row.invite_hash) == (None, None, None)
    with pytest.raises(CommandError, match="Negocio desconocido"):
        run("owner_unlink", "nobody", monkeypatch=monkeypatch)


# ── Logs never carry the chat id or the invite code ────────────────────────


def test_no_log_contains_the_chat_id_or_the_invite_code(
    tenants: Any, providers: Providers, caplog: pytest.LogCaptureFixture
) -> None:
    tenants(wa_tenant())
    code = invite("wa")
    with caplog.at_level("DEBUG"):
        post(say(OWNER_CHAT, f"/start {code}"))
        post(say(OWNER_CHAT, "hola"))
    assert str(OWNER_CHAT) not in caplog.text
    assert code not in caplog.text
