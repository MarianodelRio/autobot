from datetime import UTC, datetime, timedelta

import pytest

from core.actions import UpdateContact
from core.conversation import (
    OPT_IN_TEXT,
    OPT_OUT_TEXT,
    RECOVERY_TEXT,
    RESTART_TEXT,
    EffectiveState,
    effective_state,
    global_command,
    menu_message,
    opt_result,
    recovery_result,
)
from core.messages import IncomingMessage
from core.replies import Text

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


class TestGlobalCommand:
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
            "/start@flowpilot_dev_bot",
        ],
    )
    def test_menu(self, value: str) -> None:
        assert global_command(text(value)) == "menu"

    def test_start_equals_menu(self) -> None:
        assert global_command(text("/start")) == global_command(text("menu"))

    @pytest.mark.parametrize("value", ["baja", "BAJA", "Baja."])
    def test_opt_out(self, value: str) -> None:
        assert global_command(text(value)) == "opt_out"

    @pytest.mark.parametrize("value", ["alta", "Alta"])
    def test_opt_in(self, value: str) -> None:
        assert global_command(text(value)) == "opt_in"

    @pytest.mark.parametrize(
        "value", ["hola", "menu del dia", "quiero darme de baja", "start", "", "📅", "/startx"]
    )
    def test_other_texts_are_not_commands(self, value: str) -> None:
        assert global_command(text(value)) is None

    def test_buttons_are_not_commands(self) -> None:
        assert global_command(IncomingMessage("button", "menu", "menu", NOW)) is None

    def test_unsupported_is_not_a_command(self) -> None:
        assert global_command(IncomingMessage("unsupported", None, None, NOW)) is None


def test_menu_message_is_an_empty_text() -> None:
    assert menu_message(NOW) == IncomingMessage("text", "", None, NOW)


def test_opt_out_and_opt_in_results() -> None:
    out = opt_result("opt_out")
    assert out.replies == [Text(OPT_OUT_TEXT)]
    assert out.actions == [UpdateContact(opt_out=True)]
    assert out.state is None
    back = opt_result("opt_in")
    assert back.replies == [Text(OPT_IN_TEXT)]
    assert back.actions == [UpdateContact(opt_out=False)]


def test_recovery_result_apologises_and_resets() -> None:
    result = recovery_result()
    assert result.replies == [Text(RECOVERY_TEXT)]
    assert result.state == {}
    assert result.actions == []
