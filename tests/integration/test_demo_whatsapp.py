"""The demo bot's WhatsApp door: the same selector as tests/integration/test_demo.py
(Telegram), over WhatsApp payloads. Covers the GET subscription handshake, signature
checks, the closed `DEMO_WHATSAPP_USERS` list answering with silence (Meta bills every
message), picking a business and talking to it, and delivery statuses routed back to
the right demo tenant's outbound_message."""

import hashlib
import hmac
import itertools
import json
from collections.abc import Iterator
from typing import Any

import pytest
from django.test import Client
from pytest_django import Settings

from autobot.channels.demo import selector
from autobot.channels.demo.doors import door
from autobot.runtime import process
from autobot.runtime.models import Contact, DemoEvent, InboundEvent, OutboundMessage
from autobot.tenancy.registry import get_registry
from autobot.tenancy.tx import tenant_tx
from tests.integration.helpers import Providers, demo_tenant, drain, fixture, providers

__all__ = ["providers"]  # re-exported fixture

pytestmark = [
    pytest.mark.django_db(transaction=True, databases=["default", "owner"]),
    pytest.mark.usefixtures("clean_jobs"),
]

PHONE_NUMBER_ID = "5566778899"  # the demo door's own number, never a tenant's
OTHER_PHONE_NUMBER_ID = "1122334455"  # a foreign number: dropped by WHATSAPP.parse
APP_SECRET = "demo-wa-app-secret"
VERIFY_TOKEN = "demo-wa-verify"
USER = "34600000099"  # in DEMO_WHATSAPP_USERS
STRANGER = "34600000098"
URL = "/webhooks/whatsapp-demo"
_counter = itertools.count(1)


@pytest.fixture(autouse=True)
def demo_door(settings: Settings) -> Iterator[None]:
    settings.DEMO_WHATSAPP_PHONE_NUMBER_ID = PHONE_NUMBER_ID
    settings.DEMO_WHATSAPP_WABA_ID = "99887766"
    settings.DEMO_WHATSAPP_APP_SECRET = APP_SECRET
    settings.DEMO_WHATSAPP_ACCESS_TOKEN = "EAA-DEMO-TOKEN"
    settings.DEMO_WHATSAPP_VERIFY_TOKEN = VERIFY_TOKEN
    settings.DEMO_WHATSAPP_USERS = frozenset({USER})
    door.cache_clear()
    yield
    door.cache_clear()


def demo(slug: str = "demo-toy", **changes: Any) -> dict[str, Any]:
    return demo_tenant(slug, **changes)


def _body(template: str, phone: str, phone_number_id: str = PHONE_NUMBER_ID) -> dict[str, Any]:
    body: dict[str, Any] = json.loads(fixture(f"whatsapp/{template}"))
    value = body["entry"][0]["changes"][0]["value"]
    value["metadata"]["phone_number_id"] = phone_number_id
    message = value["messages"][0]
    message["id"] = f"wamid.demo{next(_counter)}"
    message["from"] = phone
    message.pop("from_user_id", None)
    value["contacts"][0]["wa_id"] = phone
    value["contacts"][0].pop("user_id", None)
    return body


def text_body(phone: str, text: str, **kwargs: Any) -> dict[str, Any]:
    body = _body("text.json", phone, **kwargs)
    body["entry"][0]["changes"][0]["value"]["messages"][0]["text"] = {"body": text}
    return body


def press_body(phone: str, payload: str, **kwargs: Any) -> dict[str, Any]:
    body = _body("button_reply.json", phone, **kwargs)
    message = body["entry"][0]["changes"][0]["value"]["messages"][0]
    message["interactive"]["button_reply"]["id"] = payload
    return body


def post(body: dict[str, Any], secret: str = APP_SECRET) -> int:
    raw = json.dumps(body).encode()
    signature = "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    response = Client().post(
        URL, data=raw, content_type="application/json", headers={"X-Hub-Signature-256": signature}
    )
    drain()
    return response.status_code


def say(phone: str, text: str) -> int:
    return post(text_body(phone, text))


def press(phone: str, payload: str) -> int:
    return post(press_body(phone, payload))


def wa_sent(providers: Providers, to: str) -> list[dict[str, Any]]:
    """What the demo door sent to Meta, decoded, for one recipient."""
    out = []
    for request in providers.meta:
        body = json.loads(request.content)
        if body.get("to") == to:
            out.append(body)
    return out


def wa_buttons(providers: Providers, to: str) -> list[str]:
    sent = wa_sent(providers, to)[-1]
    action = sent["interactive"]["action"]
    if "buttons" in action:
        return [b["reply"]["id"] for b in action["buttons"]]
    return [row["id"] for section in action["sections"] for row in section["rows"]]


# ── Webhook ───────────────────────────────────────────────────────────────


def test_webhook_verifies_the_subscription() -> None:
    response = Client().get(
        URL, {"hub.mode": "subscribe", "hub.verify_token": VERIFY_TOKEN, "hub.challenge": "123"}
    )
    assert (response.status_code, response.content) == (200, b"123")


def test_webhook_rejects_a_wrong_verify_token() -> None:
    response = Client().get(
        URL, {"hub.mode": "subscribe", "hub.verify_token": "wrong", "hub.challenge": "123"}
    )
    assert response.status_code == 403


def test_webhook_is_off_without_every_credential(settings: Settings) -> None:
    settings.DEMO_WHATSAPP_ACCESS_TOKEN = ""
    door.cache_clear()
    assert post(text_body(USER, "hola")) == 404
    response = Client().get(
        URL, {"hub.mode": "subscribe", "hub.verify_token": VERIFY_TOKEN, "hub.challenge": "1"}
    )
    assert response.status_code == 404


def test_a_bad_signature_is_rejected_and_counted(tenants: Any) -> None:
    tenants(demo("wa"))
    assert post(text_body(USER, "hola"), secret="wrong-secret") == 401
    assert not DemoEvent.objects.using("owner").exists()


def test_a_foreign_phone_number_id_is_dropped(tenants: Any) -> None:
    tenants(demo("wa"))
    body = text_body(USER, "hola", phone_number_id=OTHER_PHONE_NUMBER_ID)
    assert post(body) == 200  # authentic, but parse() drops it: no item to store
    assert not DemoEvent.objects.using("owner").exists()


def test_a_retry_is_stored_once(tenants: Any, providers: Providers) -> None:
    tenants(demo("wa"))
    body = text_body(USER, "hola")
    assert post(body) == 200
    assert post(body) == 200
    assert DemoEvent.objects.using("owner").count() == 1


# ── Permissions ──────────────────────────────────────────────────────────


def test_a_user_without_access_gets_no_reply(tenants: Any, providers: Providers) -> None:
    tenants(demo("wa"))
    assert say(STRANGER, "hola") == 200
    assert providers.meta == []  # WhatsApp never answers: Meta bills every message
    (event,) = DemoEvent.objects.using("owner").all()
    assert event.status == "done"


def test_an_allowed_user_sees_the_list(tenants: Any, providers: Providers) -> None:
    tenants(demo("wa"))
    say(USER, "hola")
    assert wa_buttons(providers, USER) == ["fp_select:wa", "fp_page:0"]


# ── Picking and talking ───────────────────────────────────────────────────


def test_pick_a_business_then_talk_to_it(tenants: Any, providers: Providers) -> None:
    tenants(demo("wa"))
    say(USER, "hola")
    press(USER, "fp_select:wa")
    sent = wa_sent(providers, USER)
    assert sent[-2]["text"]["body"] == "Demo · Wa. Escribe /negocio para cambiar."
    assert sent[-1]["interactive"]["body"]["text"].endswith("¿Qué quieres hacer?")
    assert wa_buttons(providers, USER) == ["greet", "color", "fail"]
    synthetic = InboundEvent.objects.using("owner").get(provider_event_id__startswith="select:")
    assert synthetic.channel == "demo_wa" and synthetic.status == "done"

    press(USER, "greet")
    assert wa_sent(providers, USER)[-1]["text"]["body"] == "¿Cómo te llamas?"
    contact = Contact.objects.using("owner").get()
    assert (contact.channel, contact.external_id, contact.phone_e164) == (
        "demo_wa",
        USER,
        f"+{USER}",
    )


def test_negocio_switches_business(tenants: Any, providers: Providers) -> None:
    tenants(demo("wa"), demo("other"))
    say(USER, "hola")
    press(USER, "fp_select:wa")
    say(USER, "/negocio")
    assert sorted(wa_buttons(providers, USER)) == ["fp_page:0", "fp_select:other", "fp_select:wa"]


def test_a_retry_of_the_same_event_does_not_repeat_the_answer(
    tenants: Any, providers: Providers
) -> None:
    tenants(demo("wa"))
    say(USER, "hola")
    (event,) = DemoEvent.objects.using("owner").all()
    before = len(providers.meta)
    selector.route_demo_event(event.id)  # already done: must answer nothing more
    assert len(providers.meta) == before


def test_proactive_reaches_only_the_whatsapp_contact(tenants: Any, providers: Providers) -> None:
    tenants(demo("wa"))
    say(USER, "hola")
    press(USER, "fp_select:wa")
    press(USER, "color")
    press(USER, "pick_1")
    proactive = OutboundMessage.objects.using("owner").get(kind="proactive")
    assert (proactive.channel, proactive.status) == ("demo_wa", "sent")
    assert wa_sent(providers, USER)[-1]["type"] == "template"


# ── Delivery statuses ────────────────────────────────────────────────────


def _post_status_only(body: dict[str, Any]) -> int:
    """Like `post`, but without `drain`: a status event is applied by `apply_status`,
    never by `process_event` (the status webhook queues it; the worker test covers the
    distinction already for a real tenant's channel)."""
    raw = json.dumps(body).encode()
    signature = "sha256=" + hmac.new(APP_SECRET.encode(), raw, hashlib.sha256).hexdigest()
    return (
        Client()
        .post(
            URL,
            data=raw,
            content_type="application/json",
            headers={"X-Hub-Signature-256": signature},
        )
        .status_code
    )


def test_a_status_updates_the_right_tenant_s_outbound_message(tenants: Any) -> None:
    tenants(demo("wa"), demo("other"))
    target = get_registry().by_slug["wa"]
    with tenant_tx(target.id):
        message = OutboundMessage.objects.create(
            tenant_id=target.id,
            contact_id=Contact.objects.create(
                tenant_id=target.id, channel="demo_wa", external_id=USER, phone_e164=f"+{USER}"
            ).id,
            channel="demo_wa",
            idem_key="k1",
            kind="proactive",
            status="sent",
        )
    body = json.loads(fixture("whatsapp/status_delivered.json"))
    value = body["entry"][0]["changes"][0]["value"]
    value["metadata"]["phone_number_id"] = PHONE_NUMBER_ID
    value["statuses"][0]["biz_opaque_callback_data"] = str(message.id)
    assert _post_status_only(body) == 200
    (event,) = InboundEvent.objects.using("owner").all()
    process.apply_status(target.id, event.id)
    with tenant_tx(target.id):
        message.refresh_from_db()
    assert message.status == "sent"  # "delivered" keeps a prior "sent" as sent


def test_an_unmatched_status_is_discarded(tenants: Any) -> None:
    tenants(demo("wa"))
    body = json.loads(fixture("whatsapp/status_delivered.json"))
    value = body["entry"][0]["changes"][0]["value"]
    value["metadata"]["phone_number_id"] = PHONE_NUMBER_ID
    value["statuses"][0]["biz_opaque_callback_data"] = "01920000-0000-7000-8000-00000000ffff"
    assert _post_status_only(body) == 200  # no crash: nothing matched, nothing stored
    assert not InboundEvent.objects.using("owner").exists()
