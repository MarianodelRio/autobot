"""Scenarios of the toy pack: they exercise the conversation harness."""

import ast
import dataclasses
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from core.actions import Action, ContactRef, NotifyOwner, SendProactive, UpdateContact
from core.conversation import OPT_OUT_TEXT, RECOVERY_TEXT, RESTART_TEXT
from core.errors import TransientError
from core.limits import LimitError
from core.messages import IncomingMessage
from core.pack import Pack, PackContext, PackResult
from core.replies import Button, Buttons, Text
from core.testing import Conversation, FixedClock, sample_tenant
from tests.toy_pack import pack as toy
from tests.toy_pack.pack import TEMPLATE_THANKS, ToyConfig

MENU = ["Saludar", "Elegir color", "Probar error"]


@pytest.fixture(params=["whatsapp", "telegram"])
def chat(request: pytest.FixtureRequest) -> Conversation:
    return Conversation(toy.pack, channel=request.param)


# ── The reference scenario, adapted to the toy pack ────────────────────────────


def test_full_conversation(chat: Conversation) -> None:
    chat.now("2026-10-05T10:00:00+02:00")
    chat.send("hola").expect(buttons=MENU)
    chat.press("color").expect(list_includes="Verde", rows=["Rojo", "Verde", "Azul", "↩️ Volver"])
    chat.press("pick_1").expect(text_contains="Has elegido Verde")
    assert chat.proactive == [
        SendProactive(
            to=ContactRef(contact_id=chat.contact.id),
            template=TEMPLATE_THANKS,
            params=["Verde"],
            button_payloads=["thanks_yes"],
            idem_key="thanks:01920000-0000-7000-8000-000000000003",
        )
    ]
    chat.press("thanks_yes").expect(text="¡Me alegro!")


def test_greeting_merges_text_into_the_menu(chat: Conversation) -> None:
    chat.send("hola")
    chat.press("greet").expect(text="¿Cómo te llamas?")
    turn = chat.send("Lucía").expect(text_contains="¡Encantado, *Lucía*!", buttons=MENU)
    assert len(turn.replies) == 1  # plan_sends put the text inside the buttons body
    assert chat.notifications == [
        NotifyOwner(
            "greeted",
            "Nuevo saludo de Lucía",
            "notify:greeted:01920000-0000-7000-8000-000000000003",
        )
    ]
    assert chat.state == {}


def test_channels_give_different_contacts() -> None:
    assert Conversation(toy.pack, channel="whatsapp").contact.phone == "+34600000001"
    assert Conversation(toy.pack, channel="telegram").contact.phone is None


# ── Common conversation rules ─────────────────────────────────────────────


@pytest.mark.parametrize("command", ["menu", "Menú", "inicio", "/start"])
def test_global_menu_resets_the_state(chat: Conversation, command: str) -> None:
    chat.send("hola")
    chat.press("greet")
    assert chat.state == {"step": "ask_name"}
    chat.send(command).expect(buttons=MENU)
    assert chat.state == {}


def test_opt_out_and_opt_in(chat: Conversation) -> None:
    chat.send("baja").expect(text=OPT_OUT_TEXT)
    assert chat.contact.opt_out
    chat.send("alta").expect(text_contains="volverás")
    assert not chat.contact.opt_out


def test_expired_conversation_starts_over(chat: Conversation) -> None:
    chat.send("hola")
    chat.press("greet")
    chat.clock.advance(minutes=31)
    chat.send("Lucía").expect(buttons=MENU)  # not taken as the name any more
    assert all(RESTART_TEXT not in r.body for r in chat.turns[-1].replies)  # silent
    assert chat.notifications == []


def test_conversation_within_30_minutes_keeps_going(chat: Conversation) -> None:
    chat.send("hola")
    chat.press("greet")
    chat.clock.advance(minutes=30)
    chat.send("Lucía").expect(text_contains="Encantado")


def test_new_state_version_restarts_with_friendly_text(chat: Conversation) -> None:
    chat.send("hola")
    chat.press("greet")
    chat.pack = dataclasses.replace(toy.pack, state_version=2)  # a deploy changed the state
    turn = chat.send("Lucía").expect(text_contains=RESTART_TEXT, buttons=MENU)
    assert len(turn.replies) == 1


def test_unsupported_message(chat: Conversation) -> None:
    chat.unsupported().expect(text_contains="Solo entiendo texto y botones", buttons=MENU)


def test_transient_error_gives_the_recovery_text(chat: Conversation) -> None:
    chat.send("hola")
    chat.press("fail").expect(text=RECOVERY_TEXT)
    assert chat.state == {}


def test_replay_reprocesses_with_the_same_idempotency_keys(chat: Conversation) -> None:
    chat.send("hola")
    chat.press("greet")
    chat.send("Lucía")
    chat.replay().expect(text_contains="Encantado")
    # The first attempt is undone and redone with the same idem_key.
    assert [n.idem_key for n in chat.notifications] == [
        "notify:greeted:01920000-0000-7000-8000-000000000003"
    ]
    assert len(chat.turns) == 3


def test_periodic_handler(chat: Conversation) -> None:
    chat.now("2026-10-05T08:00:00+02:00")
    assert chat.run_periodic("daily_summary") == [
        NotifyOwner("daily", "Resumen del día", "daily:2026-10-05")
    ]


# ── The harness catches broken packs and broken tests ────────────────────


def pack_replying(*replies: Any, state: Any = None) -> Pack:
    def handle(ctx: PackContext, msg: IncomingMessage) -> PackResult:
        return PackResult(replies=list(replies), state=state)

    return dataclasses.replace(toy.pack, handle_message=handle)


def test_reply_out_of_limits_fails_the_test() -> None:
    four = Buttons("x", [Button(str(i), f"B{i}") for i in range(4)])
    with pytest.raises(LimitError, match="4 buttons"):
        Conversation(pack_replying(four)).send("hola")


def test_text_over_4096_fails_the_test() -> None:
    with pytest.raises(LimitError, match="4097"):
        Conversation(pack_replying(Text("a" * 4097))).send("hola")


def test_state_must_be_json() -> None:
    with pytest.raises(TypeError):
        Conversation(pack_replying(Text("x"), state={"when": datetime.now()})).send("hola")


def test_pressing_something_never_offered_fails(chat: Conversation) -> None:
    chat.send("hola")
    with pytest.raises(AssertionError, match="never offered"):
        chat.press("pick_1")
    chat.press("pick_1", check=False).expect(buttons=MENU)


def test_failed_expectation_shows_the_replies(chat: Conversation) -> None:
    with pytest.raises(AssertionError, match=r"(?s)buttons are .*Saludar.*Replies:"):
        chat.send("hola").expect(buttons=["Otra cosa"])
    with pytest.raises(AssertionError, match="expected no reply"):
        chat.send("hola").expect(nothing=True)


def test_proactive_template_parameters_are_checked() -> None:
    bad = SendProactive(ContactRef(phone="+34600000001"), TEMPLATE_THANKS, [], ["thanks_yes"], "k")

    def handle(ctx: PackContext, msg: IncomingMessage) -> PackResult:
        return PackResult(replies=[Text("ok")], actions=[bad])

    with pytest.raises(AssertionError, match="other parameters"):
        Conversation(dataclasses.replace(toy.pack, handle_message=handle)).send("hola")


# ── Building blocks ───────────────────────────────────────────────────────


def test_fixed_clock() -> None:
    clock = FixedClock(
        datetime.fromisoformat("2026-10-05T10:00:00+02:00"), ZoneInfo("Europe/Madrid")
    )
    clock.advance(minutes=90)
    assert clock.now().isoformat() == "2026-10-05T11:30:00+02:00"
    with pytest.raises(ValueError):
        clock.set(datetime(2026, 10, 5))


def test_sample_tenant_and_custom_config() -> None:
    assert sample_tenant().timezone.key == "Europe/Madrid"
    chat = Conversation(toy.pack, config=ToyConfig(greeting="Buenas"))
    chat.send("hola").expect(text_contains="Buenas ¿Qué quieres hacer?")


def test_lock_keys_are_recorded() -> None:
    def handle(ctx: PackContext, msg: IncomingMessage) -> PackResult:
        with ctx.lock("cal:2026-10-09"):
            return PackResult(replies=[Text("ok")])

    chat = Conversation(dataclasses.replace(toy.pack, handle_message=handle))
    chat.send("hola")
    assert chat.locks == ["cal:2026-10-09"]


def test_clock_follows_the_tenant_zone_across_the_time_change() -> None:
    chat = Conversation(toy.pack)  # 5 October, summer time in Madrid
    assert chat.clock.now().utcoffset() == timedelta(hours=2)
    chat.clock.advance(days=30)  # 4 November, after the change on 25 October
    assert chat.clock.now().isoformat() == "2026-11-04T09:00:00+01:00"


def test_replay_undoes_contact_changes() -> None:
    calls = 0

    def rename_once(ctx: PackContext, msg: IncomingMessage) -> PackResult:
        nonlocal calls
        calls += 1
        actions: list[Action] = [UpdateContact(display_name="Otra")] if calls == 1 else []
        return PackResult(replies=[Text("ok")], actions=actions)

    chat = Conversation(dataclasses.replace(toy.pack, handle_message=rename_once))
    chat.send("hola")
    assert chat.contact.display_name == "Otra"
    chat.replay()
    assert chat.contact.display_name == "Lucía"  # the first attempt was undone
    assert chat.actions == []
    assert len(chat.turns) == 1


def test_retries_before_the_recovery_text() -> None:
    calls = 0

    def flaky(ctx: PackContext, msg: IncomingMessage) -> PackResult:
        nonlocal calls
        calls += 1
        if calls < 3:
            raise TransientError("calendar down")
        return PackResult(replies=[Text("ok")])

    chat = Conversation(dataclasses.replace(toy.pack, handle_message=flaky), attempts=3)
    chat.send("hola").expect(text="ok")
    assert calls == 3
    calls = -10  # fails on the 3 attempts of the next message
    chat.send("hola").expect(text=RECOVERY_TEXT)
    assert calls == -7


def test_pack_cannot_change_the_stored_state_by_mutating_ctx() -> None:
    def mutate(ctx: PackContext, msg: IncomingMessage) -> PackResult:
        ctx.state["items"].append(2)
        return PackResult(replies=[Text("ok")])

    chat = Conversation(dataclasses.replace(toy.pack, handle_message=mutate))
    chat.state, chat.state_version = {"items": [1]}, 1
    chat.last_inbound_at = chat.clock.now()
    chat.send("hola")
    assert chat.state == {"items": [1]}


def test_undeclared_template_fails() -> None:
    other = dataclasses.replace(TEMPLATE_THANKS, name="other")
    action = SendProactive(ContactRef(phone="+34600000001"), other, ["x"], ["y"], "k")

    def handle(ctx: PackContext, msg: IncomingMessage) -> PackResult:
        return PackResult(replies=[Text("ok")], actions=[action])

    with pytest.raises(AssertionError, match="not declared"):
        Conversation(dataclasses.replace(toy.pack, handle_message=handle)).send("hola")


def test_proactive_buttons_for_another_contact_are_not_pressable() -> None:
    action = SendProactive(
        ContactRef(phone="+34699999999"), TEMPLATE_THANKS, ["x"], ["thanks_yes"], "k"
    )

    def handle(ctx: PackContext, msg: IncomingMessage) -> PackResult:
        return PackResult(replies=[Text("ok")], actions=[action])

    chat = Conversation(dataclasses.replace(toy.pack, handle_message=handle))
    chat.send("hola")
    with pytest.raises(AssertionError, match="never offered"):
        chat.press("thanks_yes")


def test_toy_pack_only_imports_core() -> None:
    tree = ast.parse(Path(toy.__file__).read_text())
    modules = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    modules |= {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    assert {m.split(".")[0] for m in modules} <= {"core", "pydantic"}
