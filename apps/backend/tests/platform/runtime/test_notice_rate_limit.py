"""150 simultaneous owner notices against a Telegram that enforces its limits: all are
delivered, none ends `failed`. Time is simulated (a virtual clock the limiter, the fake
Telegram and the job scheduler share)."""

import heapq
import json
from collections import defaultdict, deque
from typing import Any

import httpx
import pytest
from django.utils import timezone

from autobot.channels.adapters import TELEGRAM
from autobot.runtime import notifications
from autobot.runtime.models import Notification, OwnerLink
from autobot.runtime.outbound import SendRetry
from autobot.runtime.ratelimit import SlotLimiter
from autobot.tenancy.registry import get_registry
from tests.helpers.integration import wa_tenant

pytestmark = [
    pytest.mark.django_db(transaction=True, databases=["default", "owner"]),
    pytest.mark.usefixtures("clean_jobs"),
]

BOT_LIMIT, CHAT_LIMIT = 30, 1  # messages per second at Telegram
TENANTS, PER_TENANT = 5, 30


class World:
    """A virtual clock and a Telegram that answers 429 above 30/s per bot or 1/s per chat."""

    def __init__(self) -> None:
        self.now = 1000.0
        self.window: deque[float] = deque()
        self.by_chat: dict[str, float] = defaultdict(lambda: -1e9)
        self.delivered = 0
        self.too_many = 0

    def sleep(self, seconds: float) -> None:
        self.now += seconds

    def telegram(self, request: httpx.Request) -> httpx.Response:
        chat = json.loads(request.content)["chat_id"]
        while self.window and self.window[0] <= self.now - 1.0:
            self.window.popleft()
        if len(self.window) >= BOT_LIMIT or self.now - self.by_chat[chat] < 1.0 / CHAT_LIMIT:
            self.too_many += 1
            return httpx.Response(429, json={"parameters": {"retry_after": 1}})
        self.window.append(self.now)
        self.by_chat[chat] = self.now
        self.delivered += 1
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})


def run(world: World) -> None:
    """The queue: each job runs at its time; a `SendRetry` schedules it again."""
    rows = list(Notification.objects.using("owner").filter(status="pending"))
    ready: list[tuple[float, int, Notification]] = [
        (world.now, i, row) for i, row in enumerate(rows)
    ]
    heapq.heapify(ready)
    attempts: dict[Any, int] = defaultdict(int)
    steps = 0
    while ready:
        steps += 1
        assert steps < 20_000
        at, i, row = heapq.heappop(ready)
        world.now = max(world.now, at)
        try:
            notifications.send_notification(row.tenant_id, row.id, attempts=attempts[row.id])
        except SendRetry as retry:
            attempts[row.id] += 1
            heapq.heappush(ready, (world.now + (retry.after_s or 1.0), i, row))


@pytest.fixture
def world(tenants: Any, settings: Any, monkeypatch: pytest.MonkeyPatch) -> World:
    settings.NOTIFY_BOT_TOKEN = "notification-token"
    world = World()
    docs = [wa_tenant(f"t{n}", owner={"notify": ["booking"]}) for n in range(TENANTS)]
    tenants(*docs)
    for n, doc in enumerate(docs):
        tenant = get_registry().by_slug[doc["slug"]]
        OwnerLink.objects.create(tenant_id=tenant.id, chat_id=100 + n, linked_at=timezone.now())
        for k in range(PER_TENANT):
            Notification.objects.using("owner").create(
                tenant_id=tenant.id, idem_key=f"n{k}", kind="booking", text="Hola"
            )
    monkeypatch.setattr(
        TELEGRAM, "client", httpx.Client(transport=httpx.MockTransport(world.telegram))
    )
    return world


def statuses() -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for row in Notification.objects.using("owner").all():
        counts[row.status] += 1
    return dict(counts)


def test_150_notices_with_the_limiter_are_all_delivered_without_a_429(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    limiter = SlotLimiter(
        rate_per_s=25, key_interval_s=1.0, clock=lambda: world.now, sleep=world.sleep
    )
    monkeypatch.setattr(notifications, "LIMITER", limiter)
    run(world)
    assert statuses() == {"sent": TENANTS * PER_TENANT}
    assert world.delivered == 150 and world.too_many == 0


def test_150_notices_without_the_limiter_still_all_arrive_via_retry_after(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Even if Telegram does say 429, honouring `retry_after` does not use up attempts."""
    monkeypatch.setattr(notifications, "backoff_s", lambda attempts: 1.0)
    run(world)
    assert statuses() == {"sent": TENANTS * PER_TENANT}
    assert world.too_many > 0
