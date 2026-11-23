"""Outbound by time, not by count (ADR-024): outages of a provider with an advanced clock,
the apology that replaces a stale reply, expired and revived reminders, the separate lock
of proactive sends and the provider breaker."""

import collections
import contextlib
import json
import random
import statistics
import types
from collections.abc import Iterator
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

import httpx
import pytest
from django.db import connections
from django.utils import timezone

from autobot.channels import adapters
from autobot.ops import state
from autobot.runtime import outbound, process
from autobot.runtime.breaker import MIN_TENANTS, PROBE_EVERY_S, THRESHOLD, ProviderBreaker
from autobot.runtime.locks import contact_hash
from autobot.runtime.models import Contact, OutboundMessage
from autobot.runtime.outbound import (
    APOLOGY_EVERY,
    PROACTIVE_TTL,
    REPLY_TTL,
    SendRetry,
    create_proactive,
    defer_sends,
    proactive_expiry,
    send_message,
)
from autobot.tenancy.registry import get_registry
from autobot.tenancy.tx import tenant_tx
from core.conversation import APOLOGY_TEXT
from core.proactive import ProactiveMessage
from tests.fixtures.toy_pack import pack as toy
from tests.helpers.integration import events, jobs, post_wa, wa_tenant, wa_text

pytestmark = [
    pytest.mark.django_db(transaction=True, databases=["default", "owner"]),
    pytest.mark.usefixtures("clean_jobs"),
]


class Clock:
    """`timezone.now` that only moves when the test says so."""

    def __init__(self) -> None:
        self.now = timezone.now()

    def advance(self, **delta: float) -> None:
        self.now += timedelta(**delta)


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> Clock:
    fake = Clock()
    monkeypatch.setattr(timezone, "now", lambda: fake.now)
    return fake


class Meta:
    """The provider, up or down, recording what it received."""

    def __init__(self) -> None:
        self.down = False
        self.status = 503
        self.requests: list[httpx.Request] = []

    def sent_texts(self) -> list[str]:
        return [r.content.decode() for r in self.requests if r.method == "POST"]

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.down:
            return httpx.Response(self.status, json={"error": {"code": 131016, "message": "x"}})
        if request.method == "GET":
            return httpx.Response(200, json={"id": "1"})
        return httpx.Response(200, json={"messages": [{"id": f"wamid.{len(self.requests)}"}]})


@pytest.fixture
def meta(monkeypatch: pytest.MonkeyPatch) -> Meta:
    fake = Meta()
    client = httpx.Client(transport=httpx.MockTransport(fake.handler))
    monkeypatch.setattr(adapters.WHATSAPP, "client", client)
    return fake


def tenant() -> Any:
    return get_registry().by_slug["wa"]


def reply_to(text: str = "hola") -> OutboundMessage:
    assert post_wa(wa_text(text)) == 200
    process.process_event(tenant().id, events()[-1].id, last_attempt=False)
    return OutboundMessage.objects.using("owner").order_by("-created_at").first()  # type: ignore[return-value]


def rows(**filters: Any) -> list[OutboundMessage]:
    return list(OutboundMessage.objects.using("owner").filter(**filters).order_by("created_at"))


def reload(message: OutboundMessage) -> OutboundMessage:
    return OutboundMessage.objects.using("owner").get(id=message.id)


def try_send(message: OutboundMessage) -> None:
    """One run of the job: a retry is what the worker would schedule."""
    with contextlib.suppress(SendRetry):
        send_message(tenant().id, message.id)


def run_outage(clock: Clock, until: timedelta, *, step: timedelta = timedelta(minutes=5)) -> None:
    """Every pending message of the tenant is tried every `step`, for `until`."""
    end = clock.now + until
    while clock.now < end:
        clock.advance(seconds=step.total_seconds())
        for message in rows(status="pending"):
            try_send(message)


def apologies() -> list[OutboundMessage]:
    return rows(idem_key__startswith="apology:")


def make_proactive(
    contact: Contact, key: str, *, not_after: datetime | None = None
) -> OutboundMessage:
    message = ProactiveMessage(toy.TEMPLATE_THANKS, ["Rojo"], ["thanks_yes"])
    with tenant_tx(tenant().id):
        row = create_proactive(tenant().id, contact, message, key, None, not_after=not_after)
        assert row is not None
        defer_sends(tenant().id, [row])
    return row


# ── Deadlines ────────────────────────────────────────────────────────────


def test_deadlines(tenants: Any, clock: Clock) -> None:
    tenants(wa_tenant())
    reply = reply_to()
    assert reply.expires_at == reply.created_at + REPLY_TTL == clock.now + REPLY_TTL
    now = clock.now
    assert proactive_expiry(now, None) == now + PROACTIVE_TTL
    assert proactive_expiry(now, now + timedelta(hours=3)) == now + timedelta(hours=3)
    assert proactive_expiry(now, now + timedelta(days=3)) == now + PROACTIVE_TTL


# ── Outages of a provider ────────────────────────────────────────────────


def test_a_30_minute_outage_expires_the_replies_with_one_apology_per_contact(
    tenants: Any, clock: Clock, meta: Meta
) -> None:
    tenants(wa_tenant())
    meta.down = True
    first, second = reply_to(), reply_to("hola otra vez")
    try_send(first)
    try_send(second)
    assert [m.status for m in rows(kind="reply")] == ["pending", "pending"]

    run_outage(clock, timedelta(minutes=31))
    assert [m.status for m in (reload(first), reload(second))] == ["expired", "expired"]
    (apology,) = apologies()
    assert apology.status == "pending" and apology.kind == "reply"
    assert load_text(apology) == APOLOGY_TEXT
    # The stale replies were never delivered: nothing but failed attempts reached Meta.
    assert not [m for m in rows(kind="reply") if m.status == "sent"]

    meta.down = False
    sent_before = len(meta.requests)
    try_send(apology)
    assert reload(apology).status == "sent"
    body = json.loads(meta.requests[sent_before].content)
    assert "Perdona el retraso" in body["text"]["body"]
    assert len(meta.requests) == sent_before + 1  # and the expired ones are not sent now
    try_send(first)
    assert len(meta.requests) == sent_before + 1


def load_text(message: OutboundMessage) -> str:
    from core.serialization import load_outbound

    assert message.payload is not None
    out = load_outbound(message.payload)
    return out.body  # type: ignore[union-attr]


def test_a_6_hour_outage_apologizes_once_and_reminders_are_not_apologized(
    tenants: Any, clock: Clock, meta: Meta
) -> None:
    tenants(wa_tenant())
    meta.down = True
    reply = reply_to()
    contact = Contact.objects.using("owner").get(id=reply.contact_id)
    reminder = make_proactive(contact, "reminder:a", not_after=clock.now + timedelta(hours=2))
    run_outage(clock, timedelta(hours=6), step=timedelta(minutes=10))
    assert reload(reply).status == "expired"
    assert reload(reminder).status == "expired"
    (apology,) = apologies()
    assert apology.status == "pending"  # it lasts 6 h from when it was created

    meta.down = False
    try_send(apology)
    assert reload(apology).status == "sent"
    assert apology.idem_key == f"apology:{reply.id}"  # for the reply, not for the reminder
    assert len(apologies()) == 1

    # Past the 6 h, a later lapse may apologize again.
    clock.advance(seconds=APOLOGY_EVERY.total_seconds())
    meta.down = True
    again = reply_to("hola otra vez")
    run_outage(clock, REPLY_TTL + timedelta(minutes=5))
    assert reload(again).status == "expired" and len(apologies()) == 2


def test_a_second_lapse_within_6_hours_adds_no_second_apology(
    tenants: Any, clock: Clock, meta: Meta
) -> None:
    tenants(wa_tenant())
    meta.down = True
    first = reply_to()
    run_outage(clock, REPLY_TTL + timedelta(minutes=5))
    later = reply_to("hola de nuevo")
    run_outage(clock, REPLY_TTL + timedelta(minutes=5))
    assert (reload(first).status, reload(later).status) == ("expired", "expired")
    assert len(apologies()) == 1
    # Once the 6 h have passed, the next lapse apologizes again.
    clock.advance(seconds=APOLOGY_EVERY.total_seconds())
    reply_to("hola otra vez")
    run_outage(clock, REPLY_TTL + timedelta(minutes=5))
    assert len(apologies()) == 2


def test_an_expired_apology_apologizes_for_nothing(tenants: Any, clock: Clock, meta: Meta) -> None:
    tenants(wa_tenant())
    meta.down = True
    reply_to()
    run_outage(clock, timedelta(hours=7), step=timedelta(minutes=15))
    (apology,) = apologies()
    assert apology.status == "expired" and len(apologies()) == 1


def test_reminders_are_delivered_after_the_recovery_if_the_appointment_is_ahead(
    tenants: Any, clock: Clock, meta: Meta
) -> None:
    tenants(wa_tenant())
    contact = Contact.objects.using("owner").get(id=reply_to().contact_id)
    ahead = make_proactive(contact, "reminder:ahead", not_after=clock.now + timedelta(hours=10))
    past = make_proactive(contact, "reminder:past", not_after=clock.now + timedelta(hours=2))
    meta.down = True
    run_outage(clock, timedelta(hours=3), step=timedelta(minutes=10))
    assert (reload(ahead).status, reload(past).status) == ("pending", "expired")
    meta.down = False
    try_send(ahead)
    try_send(past)
    assert (reload(ahead).status, reload(past).status) == ("sent", "expired")
    (apology,) = apologies()  # for the lapsed reply only: a reminder is not apologized for
    assert apology.contact_id == contact.id and apology.idem_key.startswith("apology:")
    assert reload(past).idem_key not in apology.idem_key


def test_a_reminder_lapses_in_24_hours_at_most(tenants: Any, clock: Clock, meta: Meta) -> None:
    tenants(wa_tenant())
    contact = Contact.objects.using("owner").get(id=reply_to().contact_id)
    reminder = make_proactive(contact, "reminder:long", not_after=clock.now + timedelta(days=5))
    meta.down = True
    run_outage(clock, timedelta(hours=25), step=timedelta(minutes=30))
    assert reload(reminder).status == "expired"


def test_rate_limits_are_always_waited_out(tenants: Any, clock: Clock, monkeypatch: Any) -> None:
    """A 429 storm: Retry-After is honoured, nothing is failed, everything gets there."""
    tenants(wa_tenant())
    answers = {"limited": True}
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if answers["limited"]:
            return httpx.Response(
                429, json={"error": {"code": 130429, "message": "x"}}, headers={"Retry-After": "7"}
            )
        return httpx.Response(200, json={"messages": [{"id": "wamid.1"}]})

    monkeypatch.setattr(
        adapters.WHATSAPP, "client", httpx.Client(transport=httpx.MockTransport(handler))
    )
    message = reply_to()
    for _ in range(12):
        with pytest.raises(SendRetry) as raised:
            send_message(tenant().id, message.id)
        assert raised.value.after_s == 7.0
        clock.advance(seconds=7)
    assert reload(message).status == "pending"
    answers["limited"] = False
    send_message(tenant().id, message.id)
    assert reload(message).status == "sent"


def test_a_retry_never_waits_past_the_expiry(tenants: Any, clock: Clock, meta: Meta) -> None:
    tenants(wa_tenant())
    meta.down = True
    message = reply_to()
    clock.advance(seconds=REPLY_TTL.total_seconds() - 3)
    with pytest.raises(SendRetry) as raised:
        send_message(tenant().id, message.id)
    assert raised.value.after_s is not None and raised.value.after_s <= 3


# ── Revival of an expired reminder ───────────────────────────────────────


def test_an_expired_reminder_is_revived_while_the_appointment_is_ahead(
    tenants: Any, clock: Clock, meta: Meta
) -> None:
    tenants(wa_tenant())
    contact = Contact.objects.using("owner").get(id=reply_to().contact_id)
    start = clock.now + timedelta(days=3)
    key = "reminder:g1"
    row = make_proactive(contact, key, not_after=start - timedelta(minutes=30))
    meta.down = True
    run_outage(clock, PROACTIVE_TTL + timedelta(hours=1), step=timedelta(minutes=30))
    assert reload(row).status == "expired"

    # The sweep offers it again, now that the provider is back (same key): it is revived.
    meta.down = False
    revived = make_proactive(contact, key, not_after=start - timedelta(minutes=30))
    assert revived.id == row.id
    back = reload(row)
    assert (back.status, back.attempts, back.last_error) == ("pending", 0, "")
    assert back.expires_at == clock.now + PROACTIVE_TTL
    try_send(back)
    assert reload(row).status == "sent"
    # Once sent it is never revived or sent twice.
    with tenant_tx(tenant().id):
        again = create_proactive(
            tenant().id,
            contact,
            ProactiveMessage(toy.TEMPLATE_THANKS, ["Rojo"], ["thanks_yes"]),
            key,
            None,
            not_after=start,
        )
    assert again is None


def test_a_reminder_that_failed_on_auth_is_revived_but_other_failures_are_not(
    tenants: Any, clock: Clock, meta: Meta
) -> None:
    """A revoked token fails the reminder; once it is fixed the sweep offers it again and
    it goes out. A recipient failure stays failed, and so does an auth failure when the
    window of the appointment is closed."""
    tenants(wa_tenant())
    contact = Contact.objects.using("owner").get(id=reply_to().contact_id)
    start = clock.now + timedelta(days=3)
    not_after = start - timedelta(minutes=30)
    row = make_proactive(contact, "reminder:auth", not_after=not_after)
    OutboundMessage.objects.using("owner").filter(id=row.id).update(
        status="failed", last_error="auth: token revoked"
    )
    revived = make_proactive(contact, "reminder:auth", not_after=not_after)
    assert revived.id == row.id
    back = reload(row)
    assert (back.status, back.attempts, back.last_error) == ("pending", 0, "")
    try_send(back)
    assert reload(row).status == "sent"

    other = make_proactive(contact, "reminder:gone", not_after=not_after)
    OutboundMessage.objects.using("owner").filter(id=other.id).update(
        status="failed", last_error="recipient: not on WhatsApp"
    )
    with tenant_tx(tenant().id):
        again = create_proactive(
            tenant().id,
            contact,
            ProactiveMessage(toy.TEMPLATE_THANKS, ["Rojo"], ["thanks_yes"]),
            "reminder:gone",
            None,
            not_after=not_after,
        )
    assert again is None and reload(other).status == "failed"

    closed = make_proactive(contact, "reminder:late", not_after=not_after)
    OutboundMessage.objects.using("owner").filter(id=closed.id).update(
        status="failed", last_error="auth: token revoked"
    )
    with tenant_tx(tenant().id):
        late = create_proactive(
            tenant().id,
            contact,
            ProactiveMessage(toy.TEMPLATE_THANKS, ["Rojo"], ["thanks_yes"]),
            "reminder:late",
            None,
            not_after=clock.now - timedelta(minutes=1),
        )
    assert late is None and reload(closed).status == "failed"


def test_an_expired_reminder_is_not_revived_once_the_appointment_is_too_close(
    tenants: Any, clock: Clock
) -> None:
    tenants(wa_tenant())
    contact = Contact.objects.using("owner").get(id=reply_to().contact_id)
    not_after = clock.now + timedelta(hours=1)
    row = make_proactive(contact, "reminder:g2", not_after=not_after)
    clock.advance(hours=2)
    try_send(row)
    assert reload(row).status == "expired"
    with tenant_tx(tenant().id):
        assert (
            create_proactive(
                tenant().id,
                contact,
                ProactiveMessage(toy.TEMPLATE_THANKS, ["Rojo"], ["thanks_yes"]),
                "reminder:g2",
                None,
                not_after=not_after,
            )
            is None
        )
    assert reload(row).status == "expired"


def test_a_rejected_reminder_is_not_revived(tenants: Any, clock: Clock) -> None:
    """`failed` means the provider refused it: asking again would only be refused again."""
    tenants(wa_tenant())
    contact = Contact.objects.using("owner").get(id=reply_to().contact_id)
    row = make_proactive(contact, "reminder:g3")
    OutboundMessage.objects.using("owner").filter(id=row.id).update(status="failed")
    with tenant_tx(tenant().id):
        assert (
            create_proactive(
                tenant().id,
                contact,
                ProactiveMessage(toy.TEMPLATE_THANKS, ["Rojo"], ["thanks_yes"]),
                "reminder:g3",
                None,
            )
            is None
        )
    assert reload(row).status == "failed"


# ── Locks ────────────────────────────────────────────────────────────────


def lock_of(message: OutboundMessage) -> str | None:
    (lock,) = [j[1] for j in jobs() if j[2].get("outbound_id") == str(message.id)]
    return lock


def test_reminders_use_their_own_lock_and_replies_keep_theirs(tenants: Any) -> None:
    tenants(wa_tenant())
    reply = reply_to()
    contact = Contact.objects.using("owner").get(id=reply.contact_id)
    reminder = make_proactive(contact, "reminder:l1")
    h = contact_hash(tenant().id, contact.channel, contact.external_id)
    assert lock_of(reply) == f"out:{h}"
    assert lock_of(reminder) == f"outp:{h}"


def test_a_stuck_reminder_does_not_block_a_reply_in_the_worker(
    tenants: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A proactive job retrying (provider says "later") holds only `outp:<h>`: a reply of the
    same contact, queued afterwards, is sent by the same worker run."""
    from django.db import connections
    from procrastinate.contrib.django.django_connector import DjangoConnector

    from autobot.runtime.jobs import OUTBOUND, app

    tenants(wa_tenant())
    reply = reply_to()
    contact = Contact.objects.using("owner").get(id=reply.contact_id)
    # Reminder first, so it is the older job; only its request is refused.
    OutboundMessage.objects.using("owner").filter(id=reply.id).update(status="sent")
    with connections["owner"].cursor() as cursor:
        cursor.execute("DELETE FROM procrastinate_jobs")
    reminder = make_proactive(contact, "reminder:l2")
    answers = iter([True, False])

    def handler(request: httpx.Request) -> httpx.Response:
        if "template" in request.content.decode() and next(answers, False):
            return httpx.Response(503, json={"error": {"code": 131016, "message": "x"}})
        return httpx.Response(200, json={"messages": [{"id": "wamid.ok"}]})

    monkeypatch.setattr(
        adapters.WHATSAPP, "client", httpx.Client(transport=httpx.MockTransport(handler))
    )
    second = reply_to("hola otra vez")
    assert isinstance(app.connector, DjangoConnector)
    with app.replace_connector(app.connector.get_worker_connector()) as worker_app:
        worker_app.run_worker(
            queues=[OUTBOUND], wait=False, install_signal_handlers=False, listen_notify=False
        )
    assert reload(second).status == "sent"
    assert reload(reminder).status == "pending"  # retrying later, on its own lock


# ── Provider breaker ─────────────────────────────────────────────────────


class FakeTime:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


def ids(n: int) -> list[UUID]:
    return [UUID(int=i + 1) for i in range(n)]


def test_the_breaker_needs_failures_from_two_tenants() -> None:
    changes: list[tuple[str, bool]] = []
    breaker = ProviderBreaker(clock=FakeTime(), on_change=lambda p, o: changes.append((p, o)))
    (only,) = ids(1)
    for _ in range(THRESHOLD * 3):
        breaker.record_failure("whatsapp", only)  # one misconfigured tenant
    assert not breaker.is_open("whatsapp") and changes == []
    breaker.record_failure("whatsapp", ids(2)[1])  # a second one confirms it
    assert breaker.is_open("whatsapp") and changes == [("whatsapp", True)]
    assert not breaker.is_open("telegram")  # per provider
    assert MIN_TENANTS == 2


def test_a_success_resets_the_count() -> None:
    breaker = ProviderBreaker(clock=FakeTime())
    a, b = ids(2)
    for _ in range(THRESHOLD - 1):
        breaker.record_failure("whatsapp", a)
    breaker.record_success("whatsapp")
    breaker.record_failure("whatsapp", b)
    assert not breaker.is_open("whatsapp")


def test_the_probe_runs_once_per_interval_and_success_closes() -> None:
    fake = FakeTime()
    changes: list[tuple[str, bool]] = []
    breaker = ProviderBreaker(clock=fake, on_change=lambda p, o: changes.append((p, o)))
    a, b = ids(2)
    for i in range(THRESHOLD):
        breaker.record_failure("whatsapp", (a, b)[i % 2])
    assert not breaker.claim_probe("whatsapp")  # not due yet
    fake.t += PROBE_EVERY_S
    assert breaker.claim_probe("whatsapp") and not breaker.claim_probe("whatsapp")
    breaker.probe_result("whatsapp", False)
    assert breaker.is_open("whatsapp")
    fake.t += PROBE_EVERY_S
    assert breaker.claim_probe("whatsapp")
    breaker.probe_result("whatsapp", True)
    assert not breaker.is_open("whatsapp")
    assert changes == [("whatsapp", True), ("whatsapp", True), ("whatsapp", False)]


@pytest.fixture
def fake_breaker(monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[ProviderBreaker, FakeTime]]:
    fake = FakeTime()
    breaker = ProviderBreaker(clock=fake, on_change=outbound._signal)
    monkeypatch.setattr(outbound, "BREAKER", breaker)
    yield breaker, fake


def test_an_open_breaker_defers_without_calling_and_a_probe_closes_it(
    tenants: Any, clock: Clock, meta: Meta, fake_breaker: Any
) -> None:
    breaker, fake = fake_breaker
    tenants(wa_tenant())
    message = reply_to()
    a, b = ids(2)
    for i in range(THRESHOLD):
        breaker.record_failure("whatsapp", (a, b)[i % 2])
    assert state.providers_down(clock.now) == ["whatsapp"]  # the one signal for ops_check

    # Open and the probe not due: no call at all, the message waits, no attempt consumed.
    with pytest.raises(SendRetry):
        send_message(tenant().id, message.id)
    assert meta.requests == []
    assert (reload(message).status, reload(message).attempts) == ("pending", 0)

    # The probe is due but the provider is still down: one read-only request, still deferred.
    meta.down = True
    fake.t += PROBE_EVERY_S
    with pytest.raises(SendRetry):
        send_message(tenant().id, message.id)
    assert [r.method for r in meta.requests] == ["GET"]
    with pytest.raises(SendRetry):  # the next probe is a minute away
        send_message(tenant().id, message.id)
    assert len(meta.requests) == 1

    # Recovered: the probe closes the breaker and the next run sends.
    meta.down = False
    fake.t += PROBE_EVERY_S
    with pytest.raises(SendRetry):
        send_message(tenant().id, message.id)
    assert not breaker.is_open("whatsapp") and state.providers_down(clock.now) == []
    send_message(tenant().id, message.id)
    assert reload(message).status == "sent"


def test_the_breaker_wait_never_goes_past_the_expiry(
    tenants: Any, clock: Clock, meta: Meta, fake_breaker: Any
) -> None:
    breaker, _ = fake_breaker
    tenants(wa_tenant())
    message = reply_to()
    OutboundMessage.objects.using("owner").filter(id=message.id).update(
        expires_at=clock.now + timedelta(seconds=3)
    )
    _open_breaker(breaker)
    with pytest.raises(SendRetry) as raised:
        send_message(tenant().id, message.id)
    assert raised.value.after_s is not None and raised.value.after_s <= 3.0


def _open_breaker(breaker: ProviderBreaker) -> None:
    a, b = ids(2)
    for i in range(THRESHOLD):
        breaker.record_failure("whatsapp", (a, b)[i % 2])


def _waits(kind: str, n: int) -> list[float]:
    ep: Any = types.SimpleNamespace(adapter=None, channel=None, secrets=None)
    return [outbound._wait_for_provider("whatsapp", ep, kind) for _ in range(n)]


def test_the_waiting_messages_are_released_spread_out_replies_first(
    fake_breaker: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """200 messages that found the breaker open do not come back at the same second: each
    waits until the probe plus a jitter, a reply's short and a reminder's longer."""
    breaker, _ = fake_breaker
    _open_breaker(breaker)
    monkeypatch.setattr(random, "uniform", random.Random(7).uniform)
    replies = _waits(OutboundMessage.Kind.REPLY, 200)
    reminders = _waits(OutboundMessage.Kind.PROACTIVE, 200)
    base = PROBE_EVERY_S
    assert all(base - 1 <= w <= base + outbound.REPLY_WAIT_SPREAD_S[1] for w in replies)
    assert all(w >= base - 1 + outbound.PROACTIVE_WAIT_SPREAD_S[0] for w in reminders)
    per_second = collections.Counter(int(w) for w in replies)
    assert max(per_second.values()) <= 20  # ~7 expected; never all 200 together
    assert len(per_second) >= 20
    assert statistics.mean(replies) < statistics.mean(reminders)
    assert max(collections.Counter(int(w) for w in reminders).values()) <= 10


def test_replies_run_before_reminders(tenants: Any, clock: Clock) -> None:
    tenants(wa_tenant())
    reply = reply_to()
    contact = Contact.objects.using("owner").get(id=reply.contact_id)
    reminder = make_proactive(contact, "reminder:prio")
    assert outbound.send_priority(reply.kind) > outbound.send_priority(reminder.kind)
    with connections["owner"].cursor() as cursor:
        cursor.execute(
            "SELECT args->>'outbound_id', priority FROM procrastinate_jobs"
            " WHERE task_name = 'send_message'"
        )
        priority = dict(cursor.fetchall())
    assert priority[str(reply.id)] == outbound.REPLY_PRIORITY
    assert priority[str(reminder.id)] == outbound.PROACTIVE_PRIORITY


def test_transport_failures_of_two_tenants_open_the_breaker_through_send_message(
    tenants: Any, clock: Clock, meta: Meta, fake_breaker: Any
) -> None:
    breaker, _ = fake_breaker
    tenants(wa_tenant("wa"), wa_tenant("wb"))
    meta.down = True
    message = reply_to()
    for _ in range(THRESHOLD - 1):
        try_send(message)
    assert not breaker.is_open("whatsapp")  # all from one tenant
    breaker.record_failure("whatsapp", get_registry().by_slug["wb"].id)
    assert breaker.is_open("whatsapp")


def test_a_4xx_never_counts_against_the_provider(
    tenants: Any, meta: Meta, fake_breaker: Any
) -> None:
    """A refusal (4xx) proves Meta is answering: it restarts the count instead of adding."""
    breaker, _ = fake_breaker
    tenants(wa_tenant("wa"), wa_tenant("wb"))
    message = reply_to()
    a, b = ids(2)
    for i in range(THRESHOLD - 1):
        breaker.record_failure("whatsapp", (a, b)[i % 2])
    meta.down, meta.status = True, 400
    send_message(tenant().id, message.id)
    assert reload(message).status == "failed"
    breaker.record_failure("whatsapp", a)
    assert not breaker.is_open("whatsapp")


def test_the_alert_callback_failure_never_breaks_a_send(
    monkeypatch: pytest.MonkeyPatch, tenants: Any
) -> None:
    def boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError("cache down")

    monkeypatch.setattr(state, "record_provider", boom)
    outbound._signal("whatsapp", True)  # logs, does not raise
