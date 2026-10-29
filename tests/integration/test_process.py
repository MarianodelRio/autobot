"""`process_event` and `apply_status` with the toy
pack and the real database. Events enter through the webhook, as in production; the job
function is then called directly (one test runs it through the worker)."""

import dataclasses
import json
from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest
from django.db import connections
from django.utils import timezone

from autobot.jobs import INBOUND, app
from autobot.runtime import process
from autobot.runtime.locks import contact_hash
from autobot.runtime.models import (
    Contact,
    Conversation,
    InboundEvent,
    MetricEvent,
    Notification,
    OutboundMessage,
)
from autobot.tenancy.registry import LoadedTenant, get_registry
from autobot.tenancy.tx import tenant_tx
from core.actions import ContactRef, RecordMetric, SendProactive
from core.conversation import OPT_IN_TEXT, OPT_OUT_TEXT, RECOVERY_TEXT, RESTART_TEXT
from core.errors import TransientError
from core.messages import IncomingMessage
from core.pack import PackContext, PackResult
from core.proactive import ProactiveMessage
from core.replies import Buttons, Reply, Text
from core.serialization import load_outbound
from tests.integration.helpers import (
    BSUID,
    events,
    fixture,
    jobs,
    post_wa,
    wa_press,
    wa_tenant,
    wa_text,
)
from tests.toy_pack import pack as toy

pytestmark = [
    pytest.mark.django_db(transaction=True, databases=["default", "owner"]),
    pytest.mark.usefixtures("clean_jobs"),
]

MENU = ["Saludar", "Elegir color", "Probar error"]


def tenant() -> LoadedTenant:
    return get_registry().by_slug["wa"]


def receive(body: bytes, *, last_attempt: bool = False) -> InboundEvent:
    """Webhook, then process_event for the event it saved."""
    before = {e.id for e in events()}
    assert post_wa(body) == 200
    (event,) = [e for e in events() if e.id not in before]
    process.process_event(tenant().id, event.id, last_attempt=last_attempt)
    return InboundEvent.objects.using("owner").get(id=event.id)


def outbound() -> list[OutboundMessage]:
    return list(OutboundMessage.objects.using("owner").order_by("created_at", "seq"))


def replies(event: InboundEvent) -> list[Reply]:
    rows = OutboundMessage.objects.using("owner").filter(inbound_event_id=event.id, kind="reply")
    out = [load_outbound(r.payload or {}) for r in rows.order_by("seq")]
    assert all(not isinstance(r, ProactiveMessage) for r in out)
    return out  # type: ignore[return-value]


def bodies(event: InboundEvent) -> list[str]:
    return [r.body for r in replies(event)]


def buttons(event: InboundEvent) -> list[str]:
    (last,) = [r for r in replies(event) if isinstance(r, Buttons)][-1:]
    return [b.title for b in last.buttons]


def contact() -> Contact:
    return Contact.objects.using("owner").get(external_id=BSUID)


def conversation() -> Conversation:
    return Conversation.objects.using("owner").get(contact_id=contact().id)


def use_pack(monkeypatch: pytest.MonkeyPatch, **changes: Any) -> None:
    monkeypatch.setattr("packs.registry.PACKS", {"toy": dataclasses.replace(toy.pack, **changes)})


# ── The happy path ────────────────────────────────────────────────────────


def test_a_message_is_answered_and_the_state_saved(tenants: Any) -> None:
    tenants(wa_tenant())
    event = receive(wa_text("hola"))
    assert (event.status, event.error) == ("done", "")
    assert event.processed_at is not None
    assert buttons(event) == MENU
    c = contact()
    assert (c.channel, c.phone_e164, c.display_name) == ("main", "+34600000001", "Lucía")
    conv = conversation()
    assert (conv.state, conv.state_version) == ({}, 1)

    event = receive(wa_press("greet"))
    assert bodies(event) == ["¿Cómo te llamas?"]
    assert conversation().state == {"step": "ask_name"}


def test_replies_are_planned_and_their_sends_queued_in_order(tenants: Any) -> None:
    tenants(wa_tenant())
    receive(wa_text("hola"))
    receive(wa_press("greet"))
    event = receive(wa_text("Lucía"))
    (reply,) = replies(event)  # the text went inside the buttons body (plan_sends)
    assert isinstance(reply, Buttons) and reply.body.startswith("¡Encantado, *Lucía*!")
    rows = OutboundMessage.objects.using("owner").filter(inbound_event_id=event.id)
    assert [(r.idem_key, r.seq, r.kind, r.status) for r in rows] == [
        (f"reply:{event.id}:0", 0, "reply", "pending")
    ]
    sends = [j for j in jobs() if j[0] == "send_message"]
    assert len(sends) == 3  # one per reply of the three turns, in order
    lock = f"out:{contact_hash(tenant().id, 'main', BSUID)}"
    assert {j[1] for j in sends} == {lock} and {j[3] for j in sends} == {"outbound"}
    assert sends[-1][2] == {"tenant_id": str(tenant().id), "outbound_id": str(rows[0].id)}


# ── Idempotency ───────────────────────────────────────────────────────────


def test_an_event_that_is_not_pending_does_nothing(tenants: Any) -> None:
    tenants(wa_tenant())
    event = receive(wa_text("hola"))
    count = len(outbound())
    process.process_event(tenant().id, event.id, last_attempt=False)  # e.g. a retry
    assert len(outbound()) == count


def test_a_retry_between_tx1_and_tx2_does_not_duplicate_replies(
    tenants: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    tenants(wa_tenant())
    assert post_wa(wa_text("hola")) == 200
    (event,) = events()

    def die(*args: object) -> None:
        raise RuntimeError("worker died before COMMIT")

    with monkeypatch.context() as patch:
        patch.setattr(process, "defer_sends", die)
        with pytest.raises(RuntimeError):
            process.process_event(tenant().id, event.id, last_attempt=False)
    assert outbound() == []  # tx2 rolled back
    assert InboundEvent.objects.using("owner").get(id=event.id).status == "pending"

    process.process_event(tenant().id, event.id, last_attempt=False)
    assert len(outbound()) == 1
    assert InboundEvent.objects.using("owner").get(id=event.id).status == "done"


def test_a_duplicate_webhook_is_answered_once(tenants: Any) -> None:
    tenants(wa_tenant())
    body = wa_text("hola")
    receive(body)
    assert post_wa(body) == 200
    assert len(events()) == 1 and len(outbound()) == 1


# ── Errors ────────────────────────────────────────────────────────────────


def test_a_transient_error_is_retried_then_recovers(tenants: Any) -> None:
    tenants(wa_tenant())
    receive(wa_text("hola"))
    assert post_wa(wa_press("fail")) == 200
    event = events()[-1]
    with pytest.raises(TransientError):  # Procrastinate retries the job
        process.process_event(tenant().id, event.id, last_attempt=False)
    assert InboundEvent.objects.using("owner").get(id=event.id).status == "pending"

    process.process_event(tenant().id, event.id, last_attempt=True)
    event = InboundEvent.objects.using("owner").get(id=event.id)
    assert (event.status, event.error) == ("failed", "TransientError on the last attempt")
    assert bodies(event) == [RECOVERY_TEXT]
    assert conversation().state == {}


def test_an_unexpected_pack_error_gives_the_recovery_text(
    tenants: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(ctx: PackContext, msg: object) -> PackResult:
        raise KeyError("bug")

    use_pack(monkeypatch, handle_message=boom)
    tenants(wa_tenant())
    event = receive(wa_text("hola"))
    assert (event.status, event.error) == ("failed", "KeyError")
    assert bodies(event) == [RECOVERY_TEXT]


# ── Conversation rules ────────────────────────────────────────────────────


def test_expiry_resets_silently(tenants: Any) -> None:
    tenants(wa_tenant())
    receive(wa_text("hola"))
    receive(wa_press("greet"))
    Conversation.objects.using("owner").update(
        last_inbound_at=timezone.now() - timedelta(minutes=31)
    )
    event = receive(wa_text("Lucía"))
    assert buttons(event) == MENU and not any("Encantado" in b for b in bodies(event))


def test_a_new_state_version_resets_with_the_friendly_text(tenants: Any) -> None:
    tenants(wa_tenant())
    receive(wa_text("hola"))
    receive(wa_press("greet"))
    Conversation.objects.using("owner").update(state_version=0)
    event = receive(wa_text("Lucía"))
    (reply,) = replies(event)
    assert isinstance(reply, Buttons) and reply.body.startswith(RESTART_TEXT)


def test_menu_command_resets_and_shows_the_menu(tenants: Any) -> None:
    tenants(wa_tenant())
    receive(wa_text("hola"))
    receive(wa_press("greet"))
    event = receive(wa_text("Menú"))
    assert buttons(event) == MENU and conversation().state == {}


def test_opt_out_and_opt_in(tenants: Any) -> None:
    tenants(wa_tenant())
    receive(wa_text("hola"))
    receive(wa_press("greet"))
    event = receive(wa_text("baja"))
    assert bodies(event) == [OPT_OUT_TEXT]
    assert contact().opt_out and contact().opt_out_at is not None
    assert conversation().state == {"step": "ask_name"}  # kept
    event = receive(wa_text("Alta"))
    assert bodies(event) == [OPT_IN_TEXT]
    assert not contact().opt_out and contact().opt_out_at is None


def test_contact_limit_saves_and_does_not_answer(tenants: Any) -> None:
    tenants(wa_tenant())
    for _ in range(20):
        receive(wa_text("hola"))
    Conversation.objects.using("owner").update(state={"step": "x"}, state_version=0)
    event = receive(wa_text("hola"))
    assert event.status == "done" and replies(event) == []  # not even the restart text


def test_a_retry_is_not_counted_twice_for_the_limit(
    tenants: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The 20th message fails once (its first attempt counts); its retry must not count
    again, or it would be the 21st hit and go unanswered."""
    failed: list[bool] = []

    def flaky(ctx: PackContext, msg: IncomingMessage) -> PackResult:
        if msg.text == "boom" and not failed:
            failed.append(True)
            raise TransientError("calendar down")
        return PackResult(replies=[Text("ok")])

    use_pack(monkeypatch, handle_message=flaky)
    tenants(wa_tenant())
    for _ in range(19):
        receive(wa_text("hola"))
    assert post_wa(wa_text("boom")) == 200
    event = events()[-1]
    with pytest.raises(TransientError):
        process.process_event(tenant().id, event.id, last_attempt=False)
    process.process_event(tenant().id, event.id, last_attempt=False, first_attempt=False)
    assert bodies(InboundEvent.objects.using("owner").get(id=event.id)) == ["ok"]


def test_the_restart_text_goes_with_global_commands(tenants: Any) -> None:
    tenants(wa_tenant())
    receive(wa_text("hola"))
    receive(wa_press("greet"))
    Conversation.objects.using("owner").update(state_version=0)
    event = receive(wa_text("baja"))
    assert bodies(event) == [f"{RESTART_TEXT}\n\n{OPT_OUT_TEXT}"]  # merged by plan_sends


def test_no_transaction_is_open_while_the_pack_runs(
    tenants: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[bool] = []

    def check(ctx: PackContext, msg: object) -> PackResult:
        seen.append(connections["default"].in_atomic_block)
        return PackResult(replies=[Text("ok")])

    use_pack(monkeypatch, handle_message=check)
    tenants(wa_tenant())
    receive(wa_text("hola"))
    assert seen == [False]


def test_a_pack_mutating_ctx_state_does_not_change_the_saved_state(
    tenants: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    def mutate(ctx: PackContext, msg: IncomingMessage) -> PackResult:
        if msg.text == "set":
            return PackResult(replies=[Text("ok")], state={"step": 1})
        ctx.state["step"] = 99  # type: ignore[index]
        return PackResult(replies=[Text("ok")])  # state=None: unchanged

    use_pack(monkeypatch, handle_message=mutate)
    tenants(wa_tenant())
    receive(wa_text("set"))
    receive(wa_text("again"))
    assert conversation().state == {"step": 1}


def test_a_degraded_tenant_answers_with_the_generic_text(tenants: Any) -> None:
    tenants(wa_tenant(config={"colors": "not a list"}))
    assert tenant().is_degraded
    event = receive(wa_text("hola"))
    assert (event.status, bodies(event)) == ("done", [process.UNAVAILABLE_TEXT])
    conv = conversation()
    assert (conv.state_version, conv.last_inbound_at) == (None, None)  # left untouched


# ── Actions ───────────────────────────────────────────────────────────────


def test_send_proactive_creates_a_proactive_message(tenants: Any) -> None:
    tenants(wa_tenant())
    receive(wa_text("hola"))
    receive(wa_press("color"))
    event = receive(wa_press("pick_1"))
    (row,) = OutboundMessage.objects.using("owner").filter(kind="proactive")
    assert row.idem_key == f"thanks:{event.id}" and row.contact_id == contact().id
    message = load_outbound(row.payload or {})
    assert isinstance(message, ProactiveMessage) and message.params == ["Verde"]
    assert sum(j[0] == "send_message" for j in jobs()) == len(outbound())


def test_no_proactive_to_an_opted_out_or_unreachable_contact(tenants: Any) -> None:
    tenants(wa_tenant())
    receive(wa_text("hola"))
    receive(wa_text("baja"))
    receive(wa_press("color"))
    receive(wa_press("pick_0"))
    assert not OutboundMessage.objects.using("owner").filter(kind="proactive").exists()

    receive(wa_text("alta"))
    Contact.objects.using("owner").update(unreachable=True)
    receive(wa_press("color"))
    receive(wa_press("pick_0"))
    assert not OutboundMessage.objects.using("owner").filter(kind="proactive").exists()


def test_no_proactive_to_a_contact_of_another_channel(
    tenants: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    tenants(wa_tenant())
    other = Contact.objects.using("owner").create(
        tenant_id=tenant().id, channel="test", external_id="100000001"
    )

    def notice(ctx: PackContext, msg: IncomingMessage) -> PackResult:
        action = SendProactive(
            to=ContactRef(contact_id=other.id),
            template=toy.TEMPLATE_THANKS,
            params=["Rojo"],
            button_payloads=["thanks_yes"],
            idem_key="x:1",
        )
        return PackResult(replies=[Text("ok")], actions=[action])

    use_pack(monkeypatch, handle_message=notice)
    get_registry.cache_clear()
    receive(wa_text("hola"))
    assert not OutboundMessage.objects.using("owner").filter(kind="proactive").exists()


def test_notify_owner_is_queued_only_if_the_owner_wants_it(tenants: Any) -> None:
    tenants(wa_tenant(owner={"notify": ["greeted"]}))
    receive(wa_text("hola"))
    receive(wa_press("greet"))
    receive(wa_text("Lucía"))
    (row,) = Notification.objects.using("owner").all()
    assert (row.kind, row.text, row.status) == ("greeted", "Nuevo saludo de Lucía", "pending")
    notify = [j for j in jobs() if j[0] == "send_notification"]
    assert [(j[1], j[2]) for j in notify] == [
        (f"owner:{tenant().id}", {"tenant_id": str(tenant().id), "notification_id": str(row.id)})
    ]


def test_notify_owner_without_owner_is_only_logged(tenants: Any) -> None:
    tenants(wa_tenant())
    receive(wa_text("hola"))
    receive(wa_press("greet"))
    receive(wa_text("Lucía"))
    assert not Notification.objects.using("owner").exists()


def test_record_metric_creates_a_metric_event(tenants: Any) -> None:
    tenants(wa_tenant())
    receive(wa_text("hola"))
    receive(wa_press("greet"))
    receive(wa_text("Lucía"))
    row = MetricEvent.objects.using("owner").get()
    assert (row.kind, row.value) == ("greeted", Decimal(1))


def test_record_metric_is_idempotent_by_idem_key(tenants: Any) -> None:
    tenants(wa_tenant())
    for _ in range(2):
        with tenant_tx(tenant().id):
            process.apply_actions(
                tenant(),
                "main",
                [RecordMetric("booking_created", "m1")],
                contact=None,
                event=None,
                now=timezone.now(),
            )
    assert MetricEvent.objects.using("owner").count() == 1


def test_proactive_to_a_phone_without_contact(
    tenants: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    def notice(ctx: PackContext, msg: object) -> PackResult:
        action = SendProactive(
            to=ContactRef(phone="+34 611 111 111"),
            template=toy.TEMPLATE_THANKS,
            params=["Rojo"],
            button_payloads=["thanks_yes"],
            idem_key="manual:abc",
        )
        return PackResult(replies=[Text("ok")], actions=[action])

    use_pack(monkeypatch, handle_message=notice)
    tenants(wa_tenant())
    receive(wa_text("hola"))
    receive(wa_text("otra vez"))  # same idem_key: not twice
    (row,) = OutboundMessage.objects.using("owner").filter(kind="proactive")
    target = Contact.objects.using("owner").get(id=row.contact_id)
    assert (target.channel, target.external_id, target.phone_e164) == (
        "main",
        "34611111111",
        "+34611111111",
    )


def test_a_phone_that_opted_out_on_its_bsuid_contact_gets_no_proactive(
    tenants: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The same person: a contact made from the phone (manual booking) and the BSUID
    contact they write from, where they said `baja`."""

    def notice(ctx: PackContext, msg: IncomingMessage) -> PackResult:
        action = SendProactive(
            to=ContactRef(phone="+34600000001"),
            template=toy.TEMPLATE_THANKS,
            params=["Rojo"],
            button_payloads=["thanks_yes"],
            idem_key=f"manual:{msg.text}",
        )
        return PackResult(replies=[Text("ok")], actions=[action])

    use_pack(monkeypatch, handle_message=notice)
    tenants(wa_tenant())
    Contact.objects.using("owner").create(
        tenant_id=tenant().id, channel="main", external_id="34600000001", phone_e164="+34600000001"
    )
    receive(wa_text("baja"))  # on the BSUID contact, which has the same phone
    receive(wa_text("uno"))
    assert not OutboundMessage.objects.using("owner").filter(kind="proactive").exists()


# ── apply_status ──────────────────────────────────────────────────────────


def status_body(name: str, ref: str, wamid: str = "wamid.OUT1", **extra: Any) -> bytes:
    body = json.loads(fixture("whatsapp/status_delivered.json"))
    status = body["entry"][0]["changes"][0]["value"]["statuses"][0]
    status.update(id=wamid, status=name, biz_opaque_callback_data=ref, **extra)
    return json.dumps(body).encode()


def apply(body: bytes) -> InboundEvent:
    before = {e.id for e in events()}
    assert post_wa(body) == 200
    (event,) = [e for e in events() if e.id not in before]
    process.apply_status(tenant().id, event.id)
    return InboundEvent.objects.using("owner").get(id=event.id)


def test_a_status_updates_its_message(tenants: Any) -> None:
    tenants(wa_tenant())
    receive(wa_text("hola"))
    (row,) = outbound()
    OutboundMessage.objects.using("owner").filter(id=row.id).update(status="unknown")

    event = apply(status_body("delivered", str(row.id)))
    assert event.status == "done"
    row.refresh_from_db(using="owner")
    assert (row.status, row.provider_message_id, row.pricing_category, row.billable) == (
        "sent",
        "wamid.OUT1",
        "service",
        True,
    )
    assert row.sent_at is not None

    apply(status_body("failed", "", errors=[{"code": 131026}]))  # found by its wamid
    row.refresh_from_db(using="owner")
    assert (row.status, row.last_error) == ("failed", "status failed: 131026")

    apply(status_body("read", str(row.id)))  # a late status never revives it
    row.refresh_from_db(using="owner")
    assert row.status == "failed"


def test_a_status_of_an_unknown_message_is_done(tenants: Any) -> None:
    tenants(wa_tenant())
    event = apply(status_body("sent", "not-a-uuid", wamid="wamid.NOBODY"))
    assert event.status == "done"


# ── Through the worker ────────────────────────────────────────────────────


def test_the_job_runs_in_the_worker(tenants: Any) -> None:
    tenants(wa_tenant())
    assert post_wa(wa_text("hola")) == 200
    connector = app.connector
    with app.replace_connector(connector.get_worker_connector()) as worker_app:  # type: ignore[attr-defined]
        worker_app.run_worker(
            queues=[INBOUND], wait=False, install_signal_handlers=False, listen_notify=False
        )
    (event,) = events()
    assert event.status == "done" and len(outbound()) == 1
    with connections["owner"].cursor() as cursor:
        cursor.execute("SELECT status FROM procrastinate_jobs WHERE task_name = 'process_event'")
        assert cursor.fetchall() == [("succeeded",)]


def test_is_last_attempt() -> None:
    from types import SimpleNamespace

    from autobot.jobs import is_last_attempt

    def ctx(attempts: int) -> Any:
        return SimpleNamespace(job=SimpleNamespace(attempts=attempts))

    assert [is_last_attempt(ctx(n)) for n in range(4)] == [False, False, False, True]
