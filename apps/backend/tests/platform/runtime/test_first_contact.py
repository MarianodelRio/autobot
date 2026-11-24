"""The first-layer privacy notice, and the retired `PERSONA`/`BAJA` commands (ADR-028),
through `process_event` with the toy pack and the real database."""

from typing import Any

import pytest

from autobot.runtime.models import Notification
from core.messages import IncomingMessage
from core.pack import PackContext, PackResult
from tests.fixtures.toy_pack import pack as toy
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

NOTICE = "_🤖 Asistente automático de Wa · Privacidad:_ https://wa.example/privacidad"


def test_the_notice_is_the_last_line_and_goes_only_once(tenants: Any) -> None:
    tenants(
        wa_tenant(
            privacy={"controller_name": "Wa S.L.", "policy_url": "https://wa.example/privacidad"}
        )
    )
    assert contact_row() is None
    first = receive(wa_text("hola"))
    (body,) = bodies(first)  # one message: the pack's menu, the notice below
    assert body.endswith(f"\n\n{NOTICE}")
    assert not body.startswith("_🤖")
    assert buttons(first)
    assert contact().notice_sent_at is not None
    assert not any("Asistente automático" in b for b in bodies(receive(wa_text("hola"))))


def test_the_notice_goes_below_the_menu_every_time(
    tenants: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A pack marks its main menu (`PackResult.menu`); the line goes below it each time,
    and only there. `notice_sent_at` keeps the first time."""

    def marking(ctx: PackContext, msg: IncomingMessage) -> PackResult:
        result = toy.handle(ctx, msg)
        result.menu = msg.payload is None and ctx.state.get("step") is None
        return result

    use_pack(monkeypatch, handle_message=marking)
    tenants(wa_tenant())
    receive(wa_text("hola"))
    first = contact().notice_sent_at
    assert "Asistente automático" not in bodies(receive(wa_press("greet")))[0]
    assert bodies(receive(wa_text("menú")))[0].endswith("_🤖 Asistente automático de Wa_")
    assert contact().notice_sent_at == first


def test_the_notice_without_configuration_is_generic(tenants: Any) -> None:
    tenants(wa_tenant())
    body = bodies(receive(wa_text("hola")))[0]
    assert body.endswith("_🤖 Asistente automático de Wa_")
    assert "http" not in body


def test_a_forgotten_contact_is_informed_again(tenants: Any) -> None:
    tenants(wa_tenant())
    receive(wa_text("hola"))
    from autobot.runtime.models import Contact

    Contact.objects.using("owner").all().delete()
    assert "Asistente automático" in bodies(receive(wa_text("hola")))[0]


@pytest.mark.parametrize("word", ["persona", "PERSONA", "baja", "STOP", "parar", "alta"])
def test_retired_command_words_reach_the_pack(tenants: Any, word: str) -> None:
    tenants(wa_tenant(owner={"notify": [], "summary_monthly": False}))
    receive(wa_text("hola"))
    receive(wa_press("greet"))
    event = receive(wa_text(word))
    # The toy pack takes it as the name it asked for: no command, no owner notice.
    assert f"¡Encantado, *{word}*!" in bodies(event)[0]
    assert conversation().state == {}
    assert not contact().opt_out
    assert Notification.objects.using("owner").count() == 0


def contact_row() -> Any:
    from autobot.runtime.models import Contact

    return Contact.objects.using("owner").first()
