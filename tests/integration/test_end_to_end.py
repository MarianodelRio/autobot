"""End to end through the real worker: webhook → queue →
worker → send, with the toy pack, the real database and queue, and the providers
answered by a mock transport. One test per failure case that does
not depend on Calendar."""

import dataclasses
import hashlib
import hmac
import json
import logging
import time
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from django.db import OperationalError, connections
from django.test import Client
from procrastinate.contrib.django.django_connector import DjangoConnector

from core.conversation import RECOVERY_TEXT
from core.messages import IncomingMessage
from core.pack import PackContext, PackResult
from flowpilot.channels import adapters, views
from flowpilot.jobs import PERIODIC, QUEUES, app
from flowpilot.runtime import process
from flowpilot.runtime.models import Contact, Conversation, OutboundMessage
from flowpilot.tenancy.registry import get_registry
from tests.integration.helpers import (
    events,
    fixture,
    post_wa,
    wa_press,
    wa_tenant,
    wa_text,
)
from tests.tenancy.helpers import WA_SECRETS
from tests.toy_pack import pack as toy

pytestmark = [
    pytest.mark.django_db(transaction=True, databases=["default", "owner"]),
    pytest.mark.usefixtures("clean_jobs"),
]

MENU_BODY = "¡Hola! ¿Qué quieres hacer?"


class Meta:
    """The Graph API: records each message sent and answers with `answer` (by default,
    accepted)."""

    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []
        self.answer: Callable[[dict[str, Any]], httpx.Response | Exception] = lambda body: (
            httpx.Response(200, json={"messages": [{"id": f"wamid.{len(self.sent)}"}]})
        )

    def handler(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.sent.append(body)
        answer = self.answer(body)
        if isinstance(answer, Exception):
            raise answer
        return answer

    def bodies(self) -> list[str]:
        out = []
        for body in self.sent:
            if body["type"] == "text":
                out.append(body["text"]["body"])
            elif body["type"] == "interactive":
                out.append(body["interactive"]["body"]["text"])
            else:
                out.append(f"template:{body['template']['name']}")
        return out


@pytest.fixture
def meta(monkeypatch: pytest.MonkeyPatch) -> Meta:
    found = Meta()
    client = httpx.Client(transport=httpx.MockTransport(found.handler))
    monkeypatch.setattr(adapters.WHATSAPP, "client", client)
    return found


def run_worker(concurrency: int = 4) -> None:
    """The worker on every queue until nothing is left to do now (scheduled retries are
    left for later). With wait=False a run stops when what is left waits on a lock, so it
    is started again."""
    assert isinstance(app.connector, DjangoConnector)
    for _ in range(30):
        with app.replace_connector(app.connector.get_worker_connector()) as worker_app:
            worker_app.run_worker(
                queues=list(QUEUES),
                concurrency=concurrency,
                wait=False,
                install_signal_handlers=False,
                listen_notify=False,
            )
        with connections["owner"].cursor() as cursor:
            cursor.execute(
                "SELECT count(*) FROM procrastinate_jobs WHERE status = 'todo'"
                " AND (scheduled_at IS NULL OR scheduled_at <= now())"
            )
            row = cursor.fetchone()
        if row is not None and row[0] == 0:
            return
    raise AssertionError("jobs left to do")


def job_statuses(task: str) -> list[str]:
    with connections["owner"].cursor() as cursor:
        cursor.execute(
            "SELECT status FROM procrastinate_jobs WHERE task_name = %s ORDER BY id", [task]
        )
        return [s for (s,) in cursor.fetchall()]


def defer_retry_stalled_jobs() -> None:
    """Queue a pass of retry_stalled_jobs, as the periodic deferrer would."""
    app.configure_task("retry_stalled_jobs", queue=PERIODIC).defer(timestamp=int(time.time()))


def with_phone_number_id(body: bytes, phone_number_id: str) -> bytes:
    data = json.loads(body)
    data["entry"][0]["changes"][0]["value"]["metadata"]["phone_number_id"] = phone_number_id
    return json.dumps(data).encode()


# ── The whole path ────────────────────────────────────────────────────────


def test_webhook_queue_worker_send(tenants: Any, meta: Meta) -> None:
    tenants(wa_tenant())
    assert post_wa(wa_text("hola")) == 200
    run_worker()
    (sent,) = meta.sent
    assert sent["to"] == "34600000001" and sent["interactive"]["body"]["text"] == MENU_BODY
    (event,) = events()
    (message,) = OutboundMessage.objects.using("owner").all()
    assert (event.status, message.status, message.provider_message_id) == (
        "done",
        "sent",
        "wamid.1",
    )
    assert set(job_statuses("process_event") + job_statuses("send_message")) == {"succeeded"}


def test_a_contacts_messages_are_answered_in_order(tenants: Any, meta: Meta) -> None:
    """Three messages arrive before the worker runs, with 4 concurrent slots: the
    conversation lock processes them one by one, and the out lock sends in order."""
    tenants(wa_tenant())
    for body in (wa_text("hola"), wa_press("greet"), wa_text("Lucía")):
        assert post_wa(body) == 200
    run_worker(concurrency=4)
    assert [b.split("\n")[0] for b in meta.bodies()] == [
        MENU_BODY,
        "¿Cómo te llamas?",
        "¡Encantado, *Lucía*!",
    ]


# ── Failure cases, one by one ──────────────────────────────────────────────────────


def test_a_duplicate_notice_is_processed_once(tenants: Any, meta: Meta) -> None:
    tenants(wa_tenant())
    body = wa_text("hola")
    assert post_wa(body) == 200
    assert post_wa(body) == 200  # Meta retried
    run_worker()
    assert len(events()) == 1 and len(meta.sent) == 1


def test_web_down_for_a_while_loses_nothing(
    tenants: Any, meta: Meta, monkeypatch: pytest.MonkeyPatch
) -> None:
    tenants(wa_tenant())
    body = wa_text("hola")
    with monkeypatch.context() as patch:

        def down(*args: object) -> None:
            raise OperationalError("database restarting")

        patch.setattr(views, "store", down)
        assert post_wa(body) == 503
    assert post_wa(body) == 200  # Meta retries
    run_worker()
    assert len(meta.sent) == 1


def test_the_worker_dies_in_the_middle_of_an_event(tenants: Any, meta: Meta) -> None:
    """A process_event left `doing` by a dead worker (no heartbeat for an hour) holds its
    contact's lock. retry_stalled_jobs puts it back: it runs again from tx1 and answers
    once, and the contact's second message, which waited behind it, follows in order.
    (That the worker defers retry_stalled_jobs is Procrastinate's periodic registry,
    checked below; with wait=False a test worker may stop before deferring it, so it is
    queued here, as its next pass would.)"""
    tenants(wa_tenant())
    assert post_wa(wa_text("hola")) == 200
    assert post_wa(wa_press("greet")) == 200
    with connections["owner"].cursor() as cursor:
        cursor.execute(
            "INSERT INTO procrastinate_workers (last_heartbeat) VALUES (now() - interval '1 hour')"
            " RETURNING id"
        )
        row = cursor.fetchone()
        assert row is not None
        cursor.execute(
            "UPDATE procrastinate_jobs SET status = 'doing', worker_id = %s WHERE id = ("
            " SELECT min(id) FROM procrastinate_jobs WHERE task_name = 'process_event')"
            " RETURNING id",
            [row[0]],
        )
        (stalled_id,) = cursor.fetchone() or (None,)
    defer_retry_stalled_jobs()
    run_worker()
    statuses = job_statuses("retry_stalled_jobs")
    assert statuses and set(statuses) == {"succeeded"}
    with connections["owner"].cursor() as cursor:
        cursor.execute(
            "SELECT status, attempts FROM procrastinate_jobs WHERE id = %s", [stalled_id]
        )
        status, attempts = cursor.fetchone() or (None, 0)
        assert status == "succeeded" and attempts >= 1  # retried
    assert [b.split("\n")[0] for b in meta.bodies()] == [MENU_BODY, "¿Cómo te llamas?"]
    assert {e.status for e in events()} == {"done"}


def test_a_send_cut_while_sending_ends_unknown_and_frees_the_contact(
    tenants: Any, meta: Meta
) -> None:
    """The worker died after committing `sending`: the retried job leaves the message
    `unknown` (never resent) and the contact's next message goes out."""
    tenants(wa_tenant())
    assert post_wa(wa_text("hola")) == 200
    run_worker()
    assert post_wa(wa_press("greet")) == 200
    with connections["owner"].cursor() as cursor:
        cursor.execute(
            "INSERT INTO procrastinate_workers (last_heartbeat) VALUES (now() - interval '1 hour')"
            " RETURNING id"
        )
        row = cursor.fetchone()
        assert row is not None
    first = OutboundMessage.objects.using("owner").get()
    # The first message is sent again by hand as if cut: back to `sending`, job `doing`.
    OutboundMessage.objects.using("owner").filter(id=first.id).update(status="sending")
    with connections["owner"].cursor() as cursor:
        cursor.execute(
            "UPDATE procrastinate_jobs SET status = 'doing', worker_id = %s"
            " WHERE task_name = 'send_message'",
            [row[0]],
        )
    sent_before = len(meta.sent)
    defer_retry_stalled_jobs()
    run_worker()
    first.refresh_from_db(using="owner")
    assert (first.status, first.last_error) == ("unknown", "interrupted while sending")
    assert meta.bodies()[sent_before:] == ["¿Cómo te llamas?"]


def test_retry_stalled_jobs_runs_every_five_minutes() -> None:
    (task,) = [
        t
        for t in app.periodic_registry.periodic_tasks.values()
        if t.task.name == "retry_stalled_jobs"
    ]
    assert task.cron == "*/5 * * * *" and task.task.queue == PERIODIC


def test_an_unexpected_pack_error_gives_the_recovery_text(
    tenants: Any, meta: Meta, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(ctx: PackContext, msg: IncomingMessage) -> PackResult:
        raise ZeroDivisionError

    monkeypatch.setattr(
        "packs.registry.PACKS", {"toy": dataclasses.replace(toy.pack, handle_message=boom)}
    )
    tenants(wa_tenant())
    assert post_wa(wa_text("hola")) == 200
    run_worker()
    assert meta.bodies() == [RECOVERY_TEXT]
    (event,) = events()
    assert (event.status, event.error) == ("failed", "ZeroDivisionError")
    assert Conversation.objects.using("owner").get().state == {}  # state reset


def test_an_ambiguous_send_is_not_resent_nor_blocks_the_next(tenants: Any, meta: Meta) -> None:
    tenants(wa_tenant())
    meta.answer = lambda body: (
        httpx.ReadTimeout("slow")
        if len(meta.sent) == 1
        else httpx.Response(200, json={"messages": [{"id": "wamid.ok"}]})
    )
    assert post_wa(wa_text("hola")) == 200
    assert post_wa(wa_press("greet")) == 200
    run_worker()
    statuses = [m.status for m in OutboundMessage.objects.using("owner").order_by("created_at")]
    assert statuses == ["unknown", "sent"] and len(meta.sent) == 2
    run_worker()  # nothing resends it
    assert len(meta.sent) == 2


def test_a_revoked_token_fails_with_an_alert(
    tenants: Any, meta: Meta, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.ERROR)
    tenants(wa_tenant())
    meta.answer = lambda body: httpx.Response(401, json={"error": {"code": 190}})
    assert post_wa(wa_text("hola")) == 200
    run_worker()
    (message,) = OutboundMessage.objects.using("owner").all()
    assert (message.status, message.last_error) == ("failed", "auth: HTTP 401, error 190")
    assert "ALERT tenant wa: channel token rejected" in caplog.text


def test_a_contact_that_cannot_receive_becomes_unreachable(tenants: Any, meta: Meta) -> None:
    tenants(wa_tenant())
    meta.answer = lambda body: httpx.Response(400, json={"error": {"code": 131026}})
    assert post_wa(wa_text("hola")) == 200
    run_worker()
    assert Contact.objects.using("owner").get().unreachable
    meta.answer = lambda body: httpx.Response(200, json={"messages": [{"id": "wamid.ok"}]})
    for body in (wa_press("color"), wa_press("pick_0")):
        assert post_wa(body) == 200
    run_worker()
    # Replies still go out (the contact wrote): the color was picked, so the pack did
    # ask for its proactive notice, which was dropped.
    assert "Elige un color" in meta.bodies() and "Has elegido Rojo." in meta.bodies()
    assert not OutboundMessage.objects.using("owner").filter(kind="proactive").exists()


def test_a_degraded_tenant_does_not_affect_another(tenants: Any, meta: Meta) -> None:
    tenants(wa_tenant("wa"), wa_tenant("bad", config={"colors": "not a list"}))
    bad = get_registry().by_slug["bad"]
    assert bad.is_degraded and not get_registry().by_slug["wa"].is_degraded
    assert post_wa(wa_text("hola")) == 200
    bad_body = with_phone_number_id(wa_text("hola"), str(bad.file.channel.phone_number_id))  # type: ignore[union-attr]
    response = Client().post(
        "/webhooks/whatsapp/pubbad0000",
        data=bad_body,
        content_type="application/json",
        headers={"X-Hub-Signature-256": _sign(bad_body)},
    )
    assert response.status_code == 200
    run_worker()
    assert sorted(meta.bodies()) == sorted([MENU_BODY, process.UNAVAILABLE_TEXT])


def test_database_down_gives_503(tenants: Any) -> None:
    """A real connection failure, not a mock: web answers 503 so the provider retries."""
    tenants(wa_tenant())
    connection = connections["default"]
    port = connection.settings_dict["PORT"]
    connection.close()
    connection.settings_dict["PORT"] = 1  # nothing listens there
    try:
        assert post_wa(fixture("whatsapp/text.json")) == 503
        assert Client().get("/health").status_code == 503
    finally:
        connection.close()
        connection.settings_dict["PORT"] = port
    assert post_wa(fixture("whatsapp/text.json")) == 200  # and it recovers
    assert len(events()) == 1


def _sign(body: bytes) -> str:
    return "sha256=" + hmac.new(WA_SECRETS["app_secret"].encode(), body, hashlib.sha256).hexdigest()
