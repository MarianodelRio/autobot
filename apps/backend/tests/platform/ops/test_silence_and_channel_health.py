"""`tenant_silent`, the daily Meta/Telegram channel checks and the external heartbeat."""

from datetime import datetime, timedelta
from typing import Any
from uuid import uuid7

import httpx
import pytest
from django.db import connections
from django.utils import timezone

from autobot.ops import check, health
from autobot.runtime.models import InboundEvent
from autobot.tenancy.registry import get_registry
from autobot.tenancy.schema import WhatsAppChannel, WhatsAppSecrets
from autobot.tenancy.tx import tenant_tx
from tests.helpers.disk import fake_disk
from tests.helpers.integration import demo_tenant, tg_tenant, wa_tenant

pytestmark = [
    pytest.mark.django_db(transaction=True, databases=["default", "owner"]),
    pytest.mark.usefixtures("clean_jobs"),
]


@pytest.fixture
def alerts(monkeypatch: pytest.MonkeyPatch, settings: Any) -> list[tuple[Any, ...]]:
    found: list[tuple[Any, ...]] = []
    settings.HEALTHCHECKS_PING_URL = ""
    settings.DEMO_TELEGRAM_TOKEN = ""
    settings.NOTIFY_BOT_TOKEN = ""
    monkeypatch.setattr(check, "send_ops_alert", lambda *args, **_: found.append(args))
    monkeypatch.setattr(health, "tenant_health", lambda tenant: [])
    fake_disk(monkeypatch, 1)
    return found


def kinds(alerts: list[tuple[Any, ...]]) -> set[str]:
    return {a[0] for a in alerts}


def inbound(slug: str, ages_h: list[float], *, kind: str = "message") -> None:
    tenant = get_registry().by_slug[slug]
    now = timezone.now()
    with tenant_tx(tenant.id):
        for age in ages_h:
            InboundEvent.objects.create(
                tenant_id=tenant.id,
                channel="main",
                kind=kind,
                provider_event_id=str(uuid7()),
                payload={},
                status="done",
                received_at=now - timedelta(hours=age),
            )


def test_silent_tenant_fires(tenants: Any, alerts: Any) -> None:
    tenants(wa_tenant())
    inbound("wa", [100, 110, 120, 130, 140, 150])  # a message every 10 h, then 100 h of nothing
    check.run()
    assert "tenant_silent" in kinds(alerts)


def test_normal_gap_does_not_fire(tenants: Any, alerts: Any) -> None:
    tenants(wa_tenant())
    inbound("wa", [10, 20, 30, 40, 50, 60])
    check.run()
    assert "tenant_silent" not in kinds(alerts)


def test_the_threshold_follows_the_tenants_own_traffic(tenants: Any, alerts: Any) -> None:
    # a message every ~5 days: 6 days of silence is normal (3 x median gap = 15 days)
    tenants(wa_tenant())
    inbound("wa", [24 * 6, 24 * 11, 24 * 16, 24 * 21, 24 * 26, 24 * 31])
    check.run()
    assert "tenant_silent" not in kinds(alerts)


def test_new_tenant_without_history_does_not_fire(tenants: Any, alerts: Any) -> None:
    tenants(wa_tenant())
    check.run()
    assert "tenant_silent" not in kinds(alerts)
    inbound("wa", [100, 101])  # a tester's couple of messages is not history
    check.run()
    assert "tenant_silent" not in kinds(alerts)


def test_status_receipts_do_not_count_as_traffic(tenants: Any, alerts: Any) -> None:
    tenants(wa_tenant())
    inbound("wa", [100, 110, 120, 130, 140, 150])
    inbound("wa", [1, 2, 3], kind="status")
    check.run()
    assert "tenant_silent" in kinds(alerts)


def test_demo_and_paused_tenants_do_not_fire(tenants: Any, alerts: Any) -> None:
    tenants(demo_tenant(), wa_tenant("paused", status="paused"))
    inbound("paused", [100, 110, 120, 130, 140, 150])
    check.run()
    assert "tenant_silent" not in kinds(alerts)


def test_disabled_channel_does_not_fire_silent(tenants: Any, alerts: Any) -> None:
    tenants(wa_tenant(), secrets={})  # no secrets: tenant_unavailable already says it
    inbound("wa", [100, 110, 120, 130, 140, 150])
    check.run()
    assert "tenant_silent" not in kinds(alerts)


def test_silent_threshold_function() -> None:
    now = datetime(2026, 1, 1)
    assert check.silent_threshold([now]) == check.SILENT_MIN
    times = [now - timedelta(days=i * 5) for i in range(4)]
    assert check.silent_threshold(times) == timedelta(days=15)


# --- WhatsApp: subscription and number ---------------------------------------------


@pytest.fixture
def graph(monkeypatch: Any) -> Any:
    original = httpx.Client

    def setup(subscribed: Any, number: Any) -> list[httpx.Request]:
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            assert not connections["default"].in_atomic_block
            seen.append(request)
            answer = subscribed if request.url.path.endswith("/subscribed_apps") else number
            if isinstance(answer, Exception):
                raise answer
            return httpx.Response(answer[0], json=answer[1])

        monkeypatch.setattr(
            httpx,
            "Client",
            lambda **kw: original(transport=httpx.MockTransport(handler), **kw),
        )
        return seen

    return setup


OURS = (200, {"data": [{"whatsapp_business_api_data": {"id": "1"}}]})
GOOD = (200, {"status": "CONNECTED", "quality_rating": "GREEN"})


def codes(tenant_slug: str = "wa") -> dict[str, str]:
    tenant = get_registry().by_slug[tenant_slug]
    assert isinstance(tenant.document.channel, WhatsAppChannel)
    assert isinstance(tenant.secrets, WhatsAppSecrets)
    return {
        i.code: i.severity
        for i in health.whatsapp_channel_health(tenant.document.channel, tenant.secrets)
    }


def test_wa_healthy(tenants: Any, graph: Any) -> None:
    tenants(wa_tenant())
    seen = graph(OURS, GOOD)
    assert codes() == {}
    assert all(r.url.path.startswith("/") and "access_token" not in str(r.url) for r in seen)


def test_wa_subscription_missing(tenants: Any, graph: Any) -> None:
    tenants(wa_tenant())
    graph((200, {"data": [{"whatsapp_business_api_data": {"id": "999"}}]}), GOOD)
    assert codes() == {"webhook_unsubscribed": "🔴"}
    graph((200, {"data": []}), GOOD)
    assert codes() == {"webhook_unsubscribed": "🔴"}


@pytest.mark.parametrize(
    ("payload", "severity"),
    [
        ({"status": "CONNECTED", "quality_rating": "YELLOW"}, "🟠"),
        ({"status": "CONNECTED", "quality_rating": "RED"}, "🔴"),
        ({"status": "RESTRICTED", "quality_rating": "GREEN"}, "🔴"),
    ],
)
def test_wa_number_quality(tenants: Any, graph: Any, payload: Any, severity: str) -> None:
    tenants(wa_tenant())
    graph(OURS, (200, {**payload, "messaging_limit_tier": "TIER_1K"}))
    assert codes() == {"number_quality": severity}


@pytest.mark.parametrize(
    ("subscribed", "number", "code"),
    [
        (httpx.ReadTimeout("slow"), GOOD, "whatsapp_unavailable"),
        (OURS, httpx.ConnectError("down"), "whatsapp_unavailable"),
        ((500, {"error": {}}), GOOD, "whatsapp_unavailable"),
        ((401, {"error": {}}), GOOD, "auth"),
        ((200, {"nonsense": 1}), GOOD, "whatsapp_unavailable"),
    ],
)
def test_wa_graph_failures_become_findings_not_exceptions(
    tenants: Any, graph: Any, subscribed: Any, number: Any, code: str
) -> None:
    tenants(wa_tenant())
    graph(subscribed, number)
    assert list(codes()) == [code]


def test_wa_checks_use_a_short_timeout(tenants: Any, monkeypatch: Any) -> None:
    tenants(wa_tenant())
    timeouts: list[Any] = []
    original = httpx.Client

    def client(**kw: Any) -> httpx.Client:
        timeouts.append(kw.get("timeout"))
        return original(
            transport=httpx.MockTransport(
                lambda r: httpx.Response(
                    200, json={"data": []} if "subscribed" in r.url.path else {}
                )
            ),
            **kw,
        )

    monkeypatch.setattr(httpx, "Client", client)
    codes()
    assert timeouts and all(t is not None and t <= 5 for t in timeouts)


def test_wa_findings_reach_ops_check_with_their_own_kinds_once_a_day(
    tenants: Any, graph: Any, settings: Any, monkeypatch: Any
) -> None:
    tenants(wa_tenant())
    settings.HEALTHCHECKS_PING_URL = ""
    settings.DEMO_TELEGRAM_TOKEN = ""
    settings.NOTIFY_BOT_TOKEN = ""
    sent: list[tuple[Any, ...]] = []
    monkeypatch.setattr(check, "send_ops_alert", lambda *a, **_: sent.append(a))
    monkeypatch.setattr(health, "whatsapp_health", lambda channel, secrets, templates: [])
    seen = graph((200, {"data": []}), (200, {"status": "CONNECTED", "quality_rating": "YELLOW"}))
    now = timezone.now()
    monkeypatch.setattr(timezone, "now", lambda: now)
    check.run()
    assert {"webhook_unsubscribed", "number_quality"} <= kinds(sent)
    first = len(seen)
    # a problem is rechecked after 15 minutes, not before
    monkeypatch.setattr(timezone, "now", lambda: now + timedelta(minutes=5))
    check.run()
    assert len(seen) == first
    # and once healthy, only once a day
    monkeypatch.setattr(timezone, "now", lambda: now + timedelta(minutes=20))
    graph(OURS, GOOD)
    sent.clear()
    check.run()
    assert not {"webhook_unsubscribed", "number_quality"} & kinds(sent)


def test_a_failing_graph_never_breaks_ops_check(
    tenants: Any, graph: Any, settings: Any, monkeypatch: Any
) -> None:
    tenants(wa_tenant(), tg_tenant())
    settings.HEALTHCHECKS_PING_URL = "https://heartbeat.invalid/x"
    settings.DEMO_TELEGRAM_TOKEN = ""
    settings.NOTIFY_BOT_TOKEN = ""
    sent: list[tuple[Any, ...]] = []
    monkeypatch.setattr(check, "send_ops_alert", lambda *a, **_: sent.append(a))
    pings: list[Any] = []

    def ok(*args: Any, **kwargs: Any) -> httpx.Response:
        pings.append(args)
        return httpx.Response(200)

    monkeypatch.setattr(httpx, "get", ok)
    graph(httpx.ReadTimeout("slow"), httpx.ReadTimeout("slow"))
    check.run()
    assert "check_failed" not in kinds(sent)
    assert len(pings) == 1


# --- Telegram -------------------------------------------------------------------------


def telegram_kinds(result: dict[str, Any], monkeypatch: Any, settings: Any) -> set[str]:
    settings.PUBLIC_URL = "https://api.example.org"
    tenant = get_registry().by_slug["tg"]
    assert tenant.document.channel is not None
    ours = f"https://api.example.org/webhooks/telegram/{tenant.document.channel.public_id}"
    original = httpx.Client
    body = {"url": ours, **result}
    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **kw: original(
            transport=httpx.MockTransport(
                lambda r: httpx.Response(200, json={"ok": True, "result": body})
            ),
            **kw,
        ),
    )
    settings.HEALTHCHECKS_PING_URL = ""
    settings.DEMO_TELEGRAM_TOKEN = ""
    settings.NOTIFY_BOT_TOKEN = ""
    sent: list[tuple[Any, ...]] = []
    monkeypatch.setattr(check, "send_ops_alert", lambda *a, **_: sent.append(a))
    check.run()
    return kinds(sent)


@pytest.mark.parametrize(
    ("result", "expected"),
    [
        ({}, None),
        ({"url": "https://old.example/x"}, "webhook_unsubscribed"),
        ({"url": ""}, "webhook_unsubscribed"),
        ({"last_error_date": 9999999999}, "webhook_errors"),
        ({"pending_update_count": 500}, "webhook_errors"),
        ({"pending_update_count": 3}, None),
    ],
)
def test_telegram_webhook_checks(
    tenants: Any, settings: Any, monkeypatch: Any, result: Any, expected: str | None
) -> None:
    tenants(tg_tenant())
    found = telegram_kinds(result, monkeypatch, settings)
    watched = {"webhook_unsubscribed", "webhook_errors"}
    assert (found & watched) == ({expected} if expected else set())


# --- External heartbeat ---------------------------------------------------------------


def test_heartbeat_is_a_plain_ping_and_its_failure_is_tolerated(
    tenants: Any, alerts: Any, settings: Any, monkeypatch: Any
) -> None:
    tenants(wa_tenant())
    settings.HEALTHCHECKS_PING_URL = "https://hc.invalid/ping/abc"
    seen: list[tuple[Any, dict[str, Any]]] = []

    def ping(*args: Any, **kwargs: Any) -> httpx.Response:
        seen.append((args, kwargs))
        raise httpx.ConnectError("down")

    monkeypatch.setattr(httpx, "get", ping)
    check.run()  # does not raise
    assert len(seen) == 1
    args, kwargs = seen[0]
    assert args == ("https://hc.invalid/ping/abc",) and set(kwargs) == {"timeout"}
