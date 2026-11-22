"""The first-layer privacy notice, `PERSONA` and the name-step question, through
`process_event` with the toy pack and the real database."""

from typing import Any

import pytest

from autobot.runtime.models import Notification
from core.conversation import HUMAN_REQUESTED
from tests.helpers.integration import wa_press, wa_tenant, wa_text
from tests.platform.runtime.test_process import (
    bodies,
    buttons,
    contact,
    conversation,
    receive,
    use_pack,
)

pytestmark = [
    pytest.mark.django_db(transaction=True, databases=["default", "owner"]),
    pytest.mark.usefixtures("clean_jobs"),
]


def test_the_notice_goes_first_and_only_once(tenants: Any) -> None:
    tenants(
        wa_tenant(
            privacy={"controller_name": "Wa S.L.", "policy_url": "https://wa.example/privacidad"}
        )
    )
    assert contact_row() is None
    first = receive(wa_text("hola"))
    (notice,) = bodies(first)  # merged into the menu's body by plan_sends
    assert "asistente automático de Wa" in notice
    assert "Responsable: Wa S.L." in notice and "https://wa.example/privacidad" in notice
    assert buttons(first)  # the pack's menu follows
    assert contact().notice_sent_at is not None
    assert not any("asistente automático" in b for b in bodies(receive(wa_text("hola"))))


def test_the_notice_without_configuration_is_generic(tenants: Any) -> None:
    tenants(wa_tenant())
    notice = bodies(receive(wa_text("hola")))[0]
    assert "Responsable: Wa." in notice and "http" not in notice


def test_a_forgotten_contact_is_informed_again(tenants: Any) -> None:
    tenants(wa_tenant())
    receive(wa_text("hola"))
    from autobot.runtime.models import Contact

    Contact.objects.using("owner").all().delete()
    assert "asistente automático" in bodies(receive(wa_text("hola")))[0]


def test_persona_notifies_the_owner_even_if_not_listed(tenants: Any) -> None:
    tenants(
        wa_tenant(
            support={"human_contact": "Llama al 600 000 000"},
            owner={"notify": [], "summary_monthly": False},
        )
    )
    receive(wa_text("hola"))
    event = receive(wa_text("Persona"))
    assert bodies(event) == ["Claro. Para hablar con una persona de Wa: Llama al 600 000 000"]
    (row,) = Notification.objects.using("owner").all()
    assert row.kind == HUMAN_REQUESTED and "600" not in row.text
    receive(wa_text("persona"))  # the same hour: no second notice
    assert Notification.objects.using("owner").count() == 1


def test_stop_is_baja(tenants: Any) -> None:
    tenants(wa_tenant())
    receive(wa_text("hola"))
    event = receive(wa_text("STOP"))
    assert "borren tus datos" in bodies(event)[0]
    assert contact().opt_out


def test_command_word_in_a_free_text_step_asks(
    tenants: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_pack(monkeypatch, expects_free_text=lambda state: state.get("step") == "ask_name")
    tenants(wa_tenant())
    receive(wa_text("hola"))
    receive(wa_press("greet"))
    event = receive(wa_text("baja"))
    assert bodies(event) == ["¿Quieres darte de baja de los avisos o es tu nombre?"]
    assert buttons(event) == ["Darme de baja", "Es mi nombre"]
    assert not contact().opt_out and conversation().state == {"step": "ask_name"}
    event = receive(wa_press("fp_name:baja"))
    assert "Baja" in bodies(event)[0]  # the toy pack greets the "name"
    assert not contact().opt_out


def contact_row() -> Any:
    from autobot.runtime.models import Contact

    return Contact.objects.using("owner").first()
