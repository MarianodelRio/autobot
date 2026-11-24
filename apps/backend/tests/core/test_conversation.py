from datetime import UTC, datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest

from core.conversation import (
    RECOVERY_TEXT,
    RESTART_TEXT,
    EffectiveState,
    effective_state,
    first_contact_notice,
    is_menu_command,
    menu_message,
    recovery_result,
    with_notice,
)
from core.limits import MAX_INTERACTIVE_BODY
from core.messages import IncomingMessage
from core.pack import TenantInfo
from core.replies import Button, Buttons, Text

NOW = datetime(2026, 10, 5, 10, 0, tzinfo=UTC)
STATE = {"step": "choose_day", "service": "corte"}


def effective(
    state: dict[str, str] = STATE, version: int | None = 1, minutes_ago: float | None = 5
) -> EffectiveState:
    last = None if minutes_ago is None else NOW - timedelta(minutes=minutes_ago)
    return effective_state(state, version, last, pack_state_version=1, timeout_min=30, now=NOW)


class TestEffectiveState:
    def test_recent_conversation_keeps_its_state(self) -> None:
        result = effective()
        assert result.state == STATE and result.reset is None and result.notices == []

    def test_state_is_a_copy(self) -> None:
        assert effective().state is not STATE

    def test_exactly_30_minutes_is_not_expired(self) -> None:
        assert effective(minutes_ago=30).state == STATE

    def test_after_30_minutes_resets_silently(self) -> None:
        result = effective(minutes_ago=30.01)
        assert result.state == {} and result.reset == "expired" and result.notices == []

    def test_other_version_resets_with_restart_text(self) -> None:
        result = effective(version=2)
        assert result.state == {} and result.reset == "version"
        assert result.notices == [Text(RESTART_TEXT)]

    def test_missing_version_counts_as_other_version(self) -> None:
        assert effective(version=None).reset == "version"

    def test_expiry_wins_over_version(self) -> None:
        assert effective(version=2, minutes_ago=60).reset == "expired"

    def test_empty_state_needs_no_reset(self) -> None:
        result = effective(state={}, version=None, minutes_ago=None)
        assert result.state == {} and result.reset is None and result.notices == []

    def test_state_without_last_message_is_expired(self) -> None:
        assert effective(minutes_ago=None).reset == "expired"


def text(value: str) -> IncomingMessage:
    return IncomingMessage("text", value, None, NOW)


class TestMenuCommand:
    @pytest.mark.parametrize(
        "value",
        [
            "menu",
            "menú",
            "Menú",
            "MENU",
            " menu ",
            "¡Menú!",
            "inicio",
            "Inicio",
            "/start",
            "/START",
            "/start ref123",
            "/start@autobot_dev_bot",
        ],
    )
    def test_menu(self, value: str) -> None:
        assert is_menu_command(text(value))

    @pytest.mark.parametrize(
        "value",
        [
            "hola",
            "menu del dia",
            "start",
            "",
            "📅",
            "/startx",
            # The retired commands (ADR-028) are plain text for the pack now.
            "baja",
            "stop",
            "parar",
            "alta",
            "persona",
            "hablar con una persona",
        ],
    )
    def test_other_texts_are_not_commands(self, value: str) -> None:
        assert not is_menu_command(text(value))

    def test_buttons_are_not_commands(self) -> None:
        assert not is_menu_command(IncomingMessage("button", "menu", "menu", NOW))

    def test_unsupported_is_not_a_command(self) -> None:
        assert not is_menu_command(IncomingMessage("unsupported", None, None, NOW))


def test_menu_message_is_an_empty_text() -> None:
    assert menu_message(NOW) == IncomingMessage("text", "", None, NOW)


def test_recovery_result_apologises_and_resets() -> None:
    result = recovery_result()
    assert result.replies == [Text(RECOVERY_TEXT)]
    assert result.state == {}
    assert result.actions == []


TENANT = TenantInfo(
    id=UUID("01920000-0000-7000-8000-00000000000a"),
    slug="peluqueria",
    name="Peluquería Lola",
    timezone=ZoneInfo("Europe/Madrid"),
)


def test_first_contact_notice_links_the_policy() -> None:
    tenant = TenantInfo(
        **{
            **TENANT.__dict__,
            "policy_url": "https://lola.example/p",
        }
    )
    # The link stays out of the italics, so no `_` sticks to it.
    assert first_contact_notice(tenant) == (
        "_🤖 Asistente automático de Peluquería Lola · Privacidad:_ https://lola.example/p"
    )


def test_first_contact_notice_without_a_link_names_only_the_business() -> None:
    assert first_contact_notice(TENANT) == "_🤖 Asistente automático de Peluquería Lola_"


NOTICE = "_🤖 aviso_"
MENU = Buttons("¿Qué necesitas?", [Button("a", "A")], header="🚌 Bus")


def test_with_notice_is_the_last_line_of_the_last_reply() -> None:
    restart = Text(RESTART_TEXT)
    assert with_notice([restart, MENU], NOTICE) == [
        restart,
        Buttons(f"¿Qué necesitas?\n\n{NOTICE}", MENU.buttons, header="🚌 Bus"),
    ]
    assert with_notice([Text("hola")], NOTICE) == [Text(f"hola\n\n{NOTICE}")]


def test_with_notice_goes_apart_when_it_does_not_fit() -> None:
    full = Buttons("x" * MAX_INTERACTIVE_BODY, [Button("a", "A")])
    assert with_notice([full], NOTICE) == [full, Text(NOTICE)]
    assert with_notice([], NOTICE) == [Text(NOTICE)]
