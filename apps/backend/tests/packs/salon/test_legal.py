"""Legal scenarios of the salon: the first-contact notice (RGPD art. 13), and the
retired `PERSONA`/`BAJA` commands (ADR-028). The notice text belongs to the platform
(`core.conversation`); here it is checked end to end with the pack."""

from core.pack import TenantInfo
from core.replies import List
from core.testing.harness import Conversation
from packs.salon.pack import pack
from packs.salon.testing import FakeCalendar
from tests.packs.salon.test_booking import choose
from tests.packs.salon.test_config import configuration


def test_the_menu_ends_with_the_notice_every_time(salon: Conversation) -> None:
    first = salon.send("hola")
    # The pack's menu with the notice as its last line: one message.
    assert len(first.replies) == 1 and isinstance(first.replies[0], List)
    body = first.replies[0].body
    assert body.endswith("_🤖 Asistente automático de Negocio de prueba_")
    assert "PERSONA" not in body and "BAJA" not in body
    # Not on other steps, and again each time the menu is shown.
    services = salon.press("menu_book")
    assert all("Asistente automático" not in r.body for r in services.replies)
    second = salon.send("menú")
    assert len(second.replies) == 1 and second.replies[0].body.endswith(body[-40:])


def test_the_notice_links_the_configured_policy() -> None:
    tenant = TenantInfo(
        **{
            **Conversation(pack, config=configuration(), calendar=FakeCalendar()).tenant.__dict__,
            "policy_url": "https://lola.example/privacidad",
        }
    )
    chat = Conversation(pack, config=configuration(), calendar=FakeCalendar(), tenant=tenant)
    body = chat.send("hola").replies[0].body
    assert body.endswith("· Privacidad:_ https://lola.example/privacidad")


def test_baja_and_persona_in_the_name_step_are_a_name(salon: Conversation) -> None:
    choose(salon)
    salon.send("Baja").expect(text_contains="confirmada")
    assert salon.calendar.created[0].summary == "Corte de pelo - Baja"
    assert all(n.kind != "human_requested" for n in salon.notifications)
