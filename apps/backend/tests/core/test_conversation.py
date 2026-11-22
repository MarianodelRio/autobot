from datetime import UTC, datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest

from core.actions import NotifyOwner, UpdateContact
from core.conversation import (
    HUMAN_REQUESTED,
    OPT_IN_TEXT,
    OPT_OUT_TEXT,
    RECOVERY_TEXT,
    RESTART_TEXT,
    EffectiveState,
    ask_result,
    command_result,
    effective_state,
    first_contact_notice,
    global_command,
    human_result,
    menu_message,
    opt_result,
    pack_message,
    recovery_result,
)
from core.messages import IncomingMessage
from core.pack import ContactInfo, TenantInfo
from core.replies import Buttons, Text

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
            "/start@autobot_dev_bot",
        ],
    )
    def test_menu(self, value: str) -> None:
        assert global_command(text(value)) == "menu"

    def test_start_equals_menu(self) -> None:
        assert global_command(text("/start")) == global_command(text("menu"))

    @pytest.mark.parametrize("value", ["baja", "BAJA", "Baja.", "stop", "STOP", "Parar"])
    def test_opt_out(self, value: str) -> None:
        assert global_command(text(value)) == "opt_out"

    @pytest.mark.parametrize("value", ["alta", "Alta"])
    def test_opt_in(self, value: str) -> None:
        assert global_command(text(value)) == "opt_in"

    @pytest.mark.parametrize(
        "value", ["PERSONA", "Persona", "humano", "Hablar con una persona", "hablar con alguien"]
    )
    def test_human(self, value: str) -> None:
        assert global_command(text(value)) == "human"

    @pytest.mark.parametrize(
        "value",
        [
            "hola",
            "menu del dia",
            "quiero darme de baja",
            "start",
            "",
            "📅",
            "/startx",
            "stop it now",
            "una persona mayor",
        ],
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


def test_command_words_ask_where_the_pack_waits_for_free_text() -> None:
    for word in ("baja", "alta", "stop", "persona", "Hablar con una persona"):
        assert global_command(text(word), free_text=True) == "ask"
    assert global_command(text("Lucía"), free_text=True) is None
    assert global_command(text("menú"), free_text=True) == "menu"
    assert global_command(text("/start"), free_text=True) == "menu"


def test_the_question_offers_the_command_or_the_name() -> None:
    (reply,) = ask_result(text("Baja")).replies
    assert isinstance(reply, Buttons)
    assert reply.body == "¿Quieres darte de baja de los avisos o es tu nombre?"
    assert [(b.id, b.title) for b in reply.buttons] == [
        ("fp_cmd:opt_out", "Darme de baja"),
        ("fp_name:baja", "Es mi nombre"),
    ]
    assert ask_result(text("PERSONA")).replies[0] == ask_result(text("persona")).replies[0]
    (human,) = ask_result(text("PERSONA")).replies
    (opt_in,) = ask_result(text("alta")).replies
    assert human.body == "¿Quieres hablar con una persona o es tu nombre?"
    assert opt_in.body == "¿Quieres volver a recibir los avisos o es tu nombre?"
    assert ask_result(text("baja")).state is None and ask_result(text("baja")).actions == []


def test_the_answer_buttons() -> None:

    def press(payload: str) -> IncomingMessage:
        return IncomingMessage("button", None, payload, NOW)

    assert global_command(press("fp_cmd:opt_out"), free_text=True) == "opt_out"
    assert global_command(press("fp_cmd:human")) == "human"
    assert global_command(press("fp_cmd:rm_rf")) is None
    assert global_command(press("fp_name:baja"), free_text=True) is None
    assert pack_message(press("fp_name:baja")) == IncomingMessage("text", "Baja", None, NOW)
    other = press("service_corte")
    assert pack_message(other) is other


TENANT = TenantInfo(
    id=UUID("01920000-0000-7000-8000-00000000000a"),
    slug="peluqueria",
    name="Peluquería Lola",
    timezone=ZoneInfo("Europe/Madrid"),
)
CONTACT = ContactInfo(
    id=UUID("01920000-0000-7000-8000-00000000000c"),
    external_id="1",
    phone=None,
    display_name="Ana",
    opt_out=False,
)


def test_first_contact_notice_with_everything_configured() -> None:
    tenant = TenantInfo(
        **{
            **TENANT.__dict__,
            "controller_name": "Lola S.L.",
            "policy_url": "https://lola.example/p",
        }
    )
    body = first_contact_notice(tenant).body
    assert "asistente automático de Peluquería Lola" in body
    assert "Responsable: Lola S.L." in body
    assert "Más información y tus derechos: https://lola.example/p." in body
    assert "*PERSONA*" in body and "*BAJA*" in body


def test_first_contact_notice_without_config_invents_nothing() -> None:
    body = first_contact_notice(TENANT).body
    assert "Responsable: Peluquería Lola." in body
    assert "http" not in body
    assert "contacta con el negocio" in body


def test_human_result_gives_the_business_contact_and_notifies_the_owner() -> None:
    tenant = TenantInfo(**{**TENANT.__dict__, "human_contact": "Tel. 600 000 000, L-V 9-14"})
    result = human_result(tenant, CONTACT, NOW)
    assert result.replies == [
        Text("Claro. Para hablar con una persona de Peluquería Lola: Tel. 600 000 000, L-V 9-14")
    ]
    assert result.state is None
    (action,) = result.actions
    assert isinstance(action, NotifyOwner) and action.kind == HUMAN_REQUESTED
    assert "Ana" in action.text and "600" not in action.text
    # One notice per contact and hour.
    assert human_result(tenant, CONTACT, NOW + timedelta(minutes=20)).actions == result.actions
    assert human_result(tenant, CONTACT, NOW + timedelta(hours=1)).actions != result.actions


def test_human_result_without_contact_details() -> None:
    (reply,) = human_result(TENANT, CONTACT, NOW).replies
    assert reply == Text(
        "Claro. Para hablar con una persona, contacta directamente con Peluquería Lola."
    )


def test_command_result_dispatch() -> None:
    assert command_result("opt_out", text("stop"), TENANT, CONTACT).actions == [
        UpdateContact(opt_out=True)
    ]
    (action,) = command_result("human", text("persona"), TENANT, CONTACT).actions
    assert isinstance(action, NotifyOwner) and action.kind == HUMAN_REQUESTED
    assert isinstance(command_result("ask", text("baja"), TENANT, CONTACT).replies[0], Buttons)


def test_opt_out_text_says_what_it_does() -> None:
    assert "avisos" in OPT_OUT_TEXT and "borren tus datos" in OPT_OUT_TEXT
