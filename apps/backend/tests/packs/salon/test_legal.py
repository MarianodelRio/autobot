"""Legal scenarios of the salon: first-contact notice, `PERSONA`, `STOP` and the
command words in the name step (RGPD art. 13, Ley 10/2025). The text itself belongs to
the platform (`core.conversation`); here it is checked end to end with the pack."""

from core.actions import NotifyOwner
from core.conversation import HUMAN_REQUESTED
from core.pack import TenantInfo
from core.replies import Buttons, List
from core.testing.harness import ChannelType, Conversation
from packs.salon.pack import pack
from packs.salon.testing import FakeCalendar
from tests.packs.salon.test_booking import choose
from tests.packs.salon.test_config import configuration


def test_first_message_is_preceded_by_the_notice_once(salon: Conversation) -> None:
    first = salon.send("hola")
    assert "asistente automático de Negocio de prueba" in first.replies[0].body
    assert "*PERSONA*" in first.replies[0].body and "*BAJA*" in first.replies[0].body
    # The notice and the pack's menu fit one message (`plan_sends` merges them).
    assert len(first.replies) == 1 and isinstance(first.replies[0], List)
    assert first.replies[0].body.startswith("Soy el asistente automático")
    second = salon.send("hola")
    assert len(second.replies) == 1 and "asistente automático" not in second.replies[0].body


def test_the_notice_cites_the_configured_controller_and_policy() -> None:
    tenant = TenantInfo(
        **{
            **Conversation(pack, config=configuration(), calendar=FakeCalendar()).tenant.__dict__,
            "controller_name": "Lola Pérez S.L.",
            "policy_url": "https://lola.example/privacidad",
        }
    )
    chat = Conversation(pack, config=configuration(), calendar=FakeCalendar(), tenant=tenant)
    body = chat.send("hola").replies[0].body
    assert "Responsable: Lola Pérez S.L." in body
    assert "https://lola.example/privacidad" in body


def test_persona_answers_with_the_business_contact_and_notifies_the_owner() -> None:
    base = Conversation(pack, config=configuration(), calendar=FakeCalendar()).tenant
    tenant = TenantInfo(**{**base.__dict__, "human_contact": "Tel. 600 000 000 (L-V 9-14 h)"})
    chat = Conversation(
        pack, config=configuration(), calendar=FakeCalendar(), tenant=tenant, notice=False
    )
    chat.send("Persona").expect(text_contains="Tel. 600 000 000 (L-V 9-14 h)")
    (notice,) = chat.notifications
    assert isinstance(notice, NotifyOwner) and notice.kind == HUMAN_REQUESTED
    assert "600" not in notice.text


def test_persona_works_in_the_middle_of_a_booking(salon: Conversation) -> None:
    salon.send("hola")
    salon.press("menu_book")
    salon.press("service_corte")
    step = salon.state["step"]
    salon.send("hablar con una persona").expect(text_contains="contacta directamente")
    assert salon.state["step"] == step  # the booking goes on


def test_stop_and_parar_are_baja(salon: Conversation) -> None:
    salon.send("hola")
    turn = salon.send("STOP").expect(text_contains="ya no te enviaré")
    assert "borren tus datos" in turn.replies[0].body
    assert salon.contact.opt_out
    salon.send("alta")
    assert not salon.contact.opt_out
    salon.send("parar")
    assert salon.contact.opt_out


def test_baja_in_the_name_step_asks_instead_of_guessing(salon: Conversation) -> None:
    choose(salon)
    turn = salon.send("Baja").expect(
        text="¿Quieres darte de baja de los avisos o es tu nombre?",
        buttons=["Darme de baja", "Es mi nombre"],
    )
    assert isinstance(turn.replies[-1], Buttons)
    assert not salon.contact.opt_out and salon.calendar.created == []
    assert salon.state["step"] == "BOOK_NAME"

    # "It is my name": the booking goes on with that name.
    salon.press("fp_name:baja").expect(text_contains="confirmada")
    assert salon.calendar.created[0].summary == "Corte de pelo - Baja"
    assert not salon.contact.opt_out


def test_baja_in_the_name_step_can_be_confirmed(salon: Conversation) -> None:
    choose(salon)
    salon.send("baja")
    salon.press("fp_cmd:opt_out").expect(text_contains="ya no te enviaré")
    assert salon.contact.opt_out
    assert salon.state["step"] == "BOOK_NAME"  # the booking can still go on
    salon.send("Lucía García").expect(text_contains="confirmada")


def test_alta_and_persona_in_the_name_step_ask_too(salon: Conversation) -> None:
    choose(salon)
    salon.send("alta").expect(text="¿Quieres volver a recibir los avisos o es tu nombre?")
    salon.send("persona").expect(text="¿Quieres hablar con una persona o es tu nombre?")
    salon.press("fp_cmd:human").expect(text_contains="contacta directamente")
    assert salon.notifications and salon.state["step"] == "BOOK_NAME"


def test_both_channels_fit_the_limits(salon: Conversation) -> None:
    channel: ChannelType = salon.channel
    assert channel in ("whatsapp", "telegram")
    choose(salon)
    salon.send("baja")  # the harness renders every reply through both adapters
