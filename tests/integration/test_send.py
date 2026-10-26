"""`send_message`: every transition, with the real adapters
answered by a mock transport and the real database."""

import json
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from django.db import connections
from django.utils import timezone
from procrastinate.contrib.django.django_connector import DjangoConnector

from flowpilot.channels import adapters
from flowpilot.jobs import OUTBOUND, SendRetryStrategy, app
from flowpilot.runtime import outbound, process
from flowpilot.runtime.models import Contact, OutboundMessage
from flowpilot.runtime.outbound import SendRetry, send_message
from flowpilot.tenancy.registry import LoadedTenant, get_registry
from tests.integration.helpers import (
    events,
    fixture,
    post_tg,
    post_wa,
    tg_tenant,
    wa_tenant,
    wa_text,
)

pytestmark = [
    pytest.mark.django_db(transaction=True, databases=["default", "owner"]),
    pytest.mark.usefixtures("clean_jobs"),
]

type Answer = httpx.Response | Exception


@pytest.fixture
def meta(monkeypatch: pytest.MonkeyPatch) -> Callable[..., list[httpx.Request]]:
    """Make Meta answer each request with the next of `answers`."""

    def setup(*answers: Answer) -> list[httpx.Request]:
        seen: list[httpx.Request] = []
        queue = list(answers)

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            answer = queue.pop(0)
            if isinstance(answer, Exception):
                raise answer
            return answer

        client = httpx.Client(transport=httpx.MockTransport(handler))
        monkeypatch.setattr(adapters.WHATSAPP, "client", client)
        monkeypatch.setattr(adapters.TELEGRAM, "client", client)
        return seen

    return setup


def ok(wamid: str = "wamid.SENT") -> httpx.Response:
    return httpx.Response(200, json={"messages": [{"id": wamid}]})


def error(status: int, code: int, **headers: str) -> httpx.Response:
    return httpx.Response(status, json={"error": {"code": code, "message": "x"}}, headers=headers)


def tenant(slug: str = "wa") -> LoadedTenant:
    return get_registry().by_slug[slug]


def a_reply(slug: str = "wa") -> OutboundMessage:
    """A message waiting to be sent: the answer to a "hola" through the webhook."""
    assert post_wa(wa_text("hola")) == 200
    process.process_event(tenant(slug).id, events()[-1].id, last_attempt=False)
    return OutboundMessage.objects.using("owner").order_by("-created_at").first()  # type: ignore[return-value]


def reload(message: OutboundMessage) -> OutboundMessage:
    return OutboundMessage.objects.using("owner").get(id=message.id)


def send(message: OutboundMessage, slug: str = "wa") -> None:
    send_message(tenant(slug).id, message.id)


# ── Transitions ───────────────────────────────────────────────────────────


def test_pending_is_sent(tenants: Any, meta: Any) -> None:
    tenants(wa_tenant())
    seen = meta(ok())
    message = a_reply()
    send(message)
    message = reload(message)
    assert (message.status, message.provider_message_id, message.attempts) == (
        "sent",
        "wamid.SENT",
        1,
    )
    assert message.sent_at is not None
    body = json.loads(seen[0].content)
    assert body["to"] == "34600000001"  # the phone, known from the webhook
    assert body["biz_opaque_callback_data"] == str(message.id)
    assert body["type"] == "interactive"


@pytest.mark.parametrize("status", ["sent", "unknown", "failed"])
def test_finished_messages_are_never_sent_again(tenants: Any, meta: Any, status: str) -> None:
    tenants(wa_tenant())
    seen = meta()
    message = a_reply()
    OutboundMessage.objects.using("owner").filter(id=message.id).update(status=status)
    send(message)
    assert seen == [] and reload(message).status == status


def test_an_orphan_sending_becomes_unknown(tenants: Any, meta: Any) -> None:
    tenants(wa_tenant())
    seen = meta()
    message = a_reply()
    OutboundMessage.objects.using("owner").filter(id=message.id).update(status="sending")
    send(message)
    assert seen == []
    message = reload(message)
    assert (message.status, message.last_error) == ("unknown", "interrupted while sending")


def test_status_is_committed_as_sending_before_the_call(
    tenants: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    tenants(wa_tenant())
    message = a_reply()
    during: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        # Another session sees the committed attempt: no transaction is open here.
        during.append(OutboundMessage.objects.using("owner").get(id=message.id).status)
        return ok()

    client = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(adapters.WHATSAPP, "client", client)
    send(message)
    assert during == ["sending"] and reload(message).status == "sent"


def test_retry_later_goes_back_to_pending_and_retries(tenants: Any, meta: Any) -> None:
    tenants(wa_tenant())
    meta(error(429, 130429, **{"Retry-After": "7"}))
    message = a_reply()
    with pytest.raises(SendRetry) as raised:
        send(message)
    assert raised.value.after_s == 7.0
    message = reload(message)
    assert (message.status, message.attempts) == ("pending", 1)


def test_after_five_attempts_retry_later_fails(tenants: Any, meta: Any) -> None:
    tenants(wa_tenant())
    meta(*[error(503, 131016)] * 5)
    message = a_reply()
    for _ in range(4):
        with pytest.raises(SendRetry):
            send(message)
    send(message)
    message = reload(message)
    assert (message.status, message.attempts) == ("failed", 5)
    assert message.last_error == "other: still refused after 5 attempts"


def test_rejected_recipient_marks_the_contact_unreachable(tenants: Any, meta: Any) -> None:
    tenants(wa_tenant())
    meta(error(400, 131026))
    message = a_reply()
    send(message)
    message = reload(message)
    assert (message.status, message.last_error) == ("failed", "recipient: HTTP 400, error 131026")
    assert Contact.objects.using("owner").get(id=message.contact_id).unreachable


def test_rejected_auth_fails_and_prepares_the_alert(
    tenants: Any, meta: Any, caplog: pytest.LogCaptureFixture
) -> None:
    tenants(wa_tenant())
    meta(error(401, 190))
    message = a_reply()
    send(message)
    message = reload(message)
    assert (message.status, message.last_error) == ("failed", "auth: HTTP 401, error 190")
    assert "ALERT tenant wa: channel token rejected" in caplog.text
    assert not Contact.objects.using("owner").get(id=message.contact_id).unreachable


def test_ambiguous_becomes_unknown(tenants: Any, meta: Any) -> None:
    tenants(wa_tenant())
    meta(httpx.ReadTimeout("slow"))
    message = a_reply()
    send(message)
    message = reload(message)
    assert (message.status, message.last_error) == ("unknown", "ReadTimeout")


def test_an_expired_payload_fails(tenants: Any, meta: Any) -> None:
    tenants(wa_tenant())
    seen = meta()
    message = a_reply()
    OutboundMessage.objects.using("owner").filter(id=message.id).update(payload=None)
    send(message)
    assert seen == [] and reload(message).status == "failed"


def test_telegram_sends_to_the_chat_id(tenants: Any, meta: Any) -> None:
    tenants(tg_tenant())
    seen = meta(httpx.Response(200, json={"ok": True, "result": {"message_id": 7}}))
    assert post_tg(fixture("telegram/message.json")) == 200
    process.process_event(tenant("tg").id, events()[-1].id, last_attempt=False)
    message = OutboundMessage.objects.using("owner").get()
    send(message, "tg")
    assert reload(message).provider_message_id == "7"
    assert json.loads(seen[0].content)["chat_id"] == "100000001"


# ── Retry strategy ────────────────────────────────────────────────────────


def test_retry_strategy() -> None:
    strategy = SendRetryStrategy()

    def decision(exception: BaseException, attempts: int) -> Any:
        job: Any = SimpleNamespace(attempts=attempts)
        return strategy.get_retry_decision(exception=exception, job=job)

    def wait_s(exception: BaseException, attempts: int) -> float:
        before = timezone.now()
        retry_at = decision(exception, attempts).retry_at
        return float(round((retry_at - before).total_seconds()))

    assert [wait_s(SendRetry(None), n) for n in range(4)] == [2, 4, 8, 16]
    assert wait_s(SendRetry(6.2), 0) == 7  # retry_after, rounded up
    assert decision(SendRetry(None), 5) is None  # the message is failed by then
    assert decision(RuntimeError("bug"), 0) is None


def test_a_delivery_status_that_comes_first_is_not_overwritten(
    tenants: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    tenants(wa_tenant())
    message = a_reply()

    def handler(request: httpx.Request) -> httpx.Response:
        # Meta's failed status is applied while our request is still waiting.
        OutboundMessage.objects.using("owner").filter(id=message.id).update(
            status="failed", last_error="status failed: 131026"
        )
        return ok("wamid.LATE")

    monkeypatch.setattr(
        adapters.WHATSAPP, "client", httpx.Client(transport=httpx.MockTransport(handler))
    )
    send(message)
    message = reload(message)
    assert (message.status, message.provider_message_id) == ("failed", "wamid.LATE")


def test_a_render_error_leaves_the_message_pending(
    tenants: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    tenants(wa_tenant())
    message = a_reply()

    def broken(*args: object) -> dict[str, Any]:
        raise ValueError("bad payload")

    monkeypatch.setattr(adapters.WHATSAPP, "render", broken)
    with pytest.raises(ValueError):
        send(message)
    assert (reload(message).status, reload(message).attempts) == ("pending", 0)


# ── Through the worker: unknown does not block the next message ───────────


def test_an_unknown_message_does_not_block_the_next_ones(tenants: Any, meta: Any) -> None:
    tenants(wa_tenant())
    seen = meta(httpx.ReadTimeout("slow"), ok("wamid.2"))
    assert post_wa(wa_text("hola")) == 200
    assert post_wa(wa_text("hola")) == 200
    for event in events():
        process.process_event(tenant().id, event.id, last_attempt=False)
    assert isinstance(app.connector, DjangoConnector)
    with app.replace_connector(app.connector.get_worker_connector()) as worker_app:
        worker_app.run_worker(
            queues=[OUTBOUND], wait=False, install_signal_handlers=False, listen_notify=False
        )
    rows = OutboundMessage.objects.using("owner").order_by("created_at")
    assert [r.status for r in rows] == ["unknown", "sent"]
    assert len(seen) == 2
    with connections["owner"].cursor() as cursor:
        cursor.execute("SELECT status FROM procrastinate_jobs WHERE task_name = 'send_message'")
        assert sorted(s for (s,) in cursor.fetchall()) == ["succeeded", "succeeded"]


def test_retry_later_holds_the_contacts_next_message(tenants: Any, meta: Any) -> None:
    """The first reply is retried (Retry-After: 0) and still goes out before the second."""
    tenants(wa_tenant())
    seen = meta(error(429, 130429, **{"Retry-After": "0"}), ok("wamid.1"), ok("wamid.2"))
    assert post_wa(wa_text("hola")) == 200
    assert post_wa(wa_text("menu")) == 200
    for event in events():
        process.process_event(tenant().id, event.id, last_attempt=False)
    first, second = OutboundMessage.objects.using("owner").order_by("created_at")
    assert isinstance(app.connector, DjangoConnector)
    for _ in range(5):  # a run stops when what is left waits for its scheduled time
        with app.replace_connector(app.connector.get_worker_connector()) as worker_app:
            worker_app.run_worker(
                queues=[OUTBOUND], wait=False, install_signal_handlers=False, listen_notify=False
            )
        if reload(second).status == "sent":
            break
    ids = [json.loads(r.content)["biz_opaque_callback_data"] for r in seen]
    assert ids == [str(first.id), str(first.id), str(second.id)]
    assert [reload(first).status, reload(second).status] == ["sent", "sent"]


def test_send_recipient_prefers_the_phone() -> None:
    with_phone = Contact(external_id="ES.1", phone_e164="+34600000001")
    assert outbound._recipient(with_phone) == "+34600000001"
    assert outbound._recipient(Contact(external_id="ES.1")) == "ES.1"


def test_unknown_time_and_original_event_context(tenants: Any, meta: Any, monkeypatch: Any) -> None:
    from datetime import timedelta

    from flowpilot.ops.logging import before_send

    tenants(wa_tenant())
    row = a_reply()
    OutboundMessage.objects.using("owner").filter(id=row.id).update(
        created_at=timezone.now() - timedelta(days=2)
    )
    contexts = []

    def handler(request: httpx.Request) -> httpx.Response:
        contexts.append(before_send({}, {}))
        raise httpx.ReadTimeout("secret")

    monkeypatch.setattr(
        adapters.WHATSAPP, "client", httpx.Client(transport=httpx.MockTransport(handler))
    )
    send(row)
    saved = reload(row)
    assert saved.status == "unknown" and saved.unknown_at is not None
    assert timezone.now() - saved.unknown_at < timedelta(seconds=10)
    assert contexts[0]["tags"] == {
        "tenant": "wa",
        "channel": "main",
        "event_id": str(row.inbound_event_id),
        "job": "send_message",
    }
