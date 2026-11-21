"""Webhooks and /health: every branch of the entry,
against the real database. Transactional, because the tenant rows are written by
fp_owner and the webhook reads them as fp_app."""

import json
from typing import Any

import httpx
import pytest
from django.db import DataError, OperationalError
from django.test import Client
from procrastinate.exceptions import ProcrastinateException
from procrastinate.jobs import JobDeferrer

from autobot.channels import views
from autobot.runtime.locks import conversation_lock
from autobot.runtime.models import InboundEvent
from autobot.tenancy.registry import get_registry
from autobot.tenancy.tx import tenant_tx
from tests.helpers.integration import (
    BSUID,
    WA_URL,
    events,
    fixture,
    jobs,
    post_tg,
    post_wa,
    tg_tenant,
    wa_tenant,
)
from tests.platform.tenancy.helpers import WA_SECRETS

pytestmark = [
    pytest.mark.django_db(transaction=True, databases=["default", "owner"]),
    pytest.mark.usefixtures("clean_jobs"),
]


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """A webhook never calls an external service."""

    def refuse(*args: object, **kwargs: object) -> None:
        raise AssertionError("the webhook made an external call")

    monkeypatch.setattr(httpx.Client, "send", refuse)


# ── 1. Tenant ─────────────────────────────────────────────────────────────


def test_unknown_or_disabled_channels_are_404(tenants: Any) -> None:
    tenants(wa_tenant(), tg_tenant(), secrets={"wa": WA_SECRETS})  # tg has no secrets
    assert (
        Client()
        .post("/webhooks/whatsapp/nobody000", data=b"{}", content_type="application/json")
        .status_code
        == 404
    )
    assert (
        Client()
        .post("/webhooks/telegram/pubwa0000", data=b"{}", content_type="application/json")
        .status_code
        == 404
    )
    assert post_tg(fixture("telegram/message.json")) == 404
    assert events() == []


# ── 2. Size and JSON ──────────────────────────────────────────────────────


def test_oversized_bodies_are_400_without_saving(tenants: Any) -> None:
    tenants(wa_tenant())
    assert post_wa(b'{"x": "' + b"a" * 256 * 1024 + b'"}') == 400
    assert events() == []


def test_invalid_json_is_400_after_the_signature(tenants: Any) -> None:
    tenants(wa_tenant())
    assert post_wa(b"not json") == 400
    assert post_wa(b"[1, 2]") == 400
    assert post_wa(b"not json", secret="wrong") == 401  # authenticity comes first


# ── 3. Authenticity and the IP limit ──────────────────────────────────────


def test_invalid_signatures_are_401_then_429_but_a_valid_one_always_passes(tenants: Any) -> None:
    tenants(wa_tenant())
    body = fixture("whatsapp/text.json")
    for _ in range(20):
        assert post_wa(body, secret="wrong") == 401
    assert post_wa(body, secret="wrong") == 429  # the limit of (IP, tenant) is reached
    assert post_wa(body) == 200  # a valid signature is never refused, from that IP too
    assert post_wa(body, secret="wrong", ip="198.51.100.7") == 401  # other IPs: own count
    assert len(events()) == 1


def test_a_tenant_with_a_wrong_secret_does_not_block_another_on_the_same_ip(tenants: Any) -> None:
    tenants(wa_tenant())
    tenants(tg_tenant())
    body = fixture("whatsapp/text.json")
    for _ in range(21):
        post_wa(body, secret="wrong", ip="198.51.100.9")
    assert post_wa(body, secret="wrong", ip="198.51.100.9") == 429
    # Telegram's tenant, same IP: its own count, and valid requests pass in any case
    assert (
        post_tg(fixture("telegram/message.json"), secret="w" * 31 + "x", ip="198.51.100.9") == 401
    )
    assert post_tg(fixture("telegram/message.json"), ip="198.51.100.9") == 200


def test_telegram_secret_token(tenants: Any) -> None:
    tenants(tg_tenant())
    assert post_tg(fixture("telegram/message.json"), secret="w" * 31 + "x") == 401
    assert events() == []
    assert post_tg(fixture("telegram/message.json")) == 200
    assert [e.provider_event_id for e in events()] == ["810000001"]


# ── 4. Offboarded ─────────────────────────────────────────────────────────


def test_offboarded_answers_200_without_saving(tenants: Any) -> None:
    tenants(wa_tenant(status="offboarded"))
    assert post_wa(fixture("whatsapp/text.json")) == 200
    assert events() == [] and jobs() == []


# ── 5. Save and queue ─────────────────────────────────────────────────────


def test_a_message_is_saved_and_queued_with_its_conversation_lock(tenants: Any) -> None:
    tenants(wa_tenant())
    assert post_wa(fixture("whatsapp/text.json")) == 200
    (event,) = events()
    assert (event.channel, event.kind, event.status) == ("main", "message", "pending")
    assert event.payload is not None
    message = event.payload["entry"][0]["changes"][0]["value"]["messages"][0]
    assert message["id"] == event.provider_event_id
    tenant = get_registry().by_slug["wa"]
    assert jobs() == [
        (
            "process_event",
            conversation_lock(tenant.id, "main", BSUID),
            {"tenant_id": str(tenant.id), "event_id": str(event.id)},
            "inbound",
        )
    ]
    (lock,) = [j[1] for j in jobs()]
    assert lock is not None and BSUID not in lock and "34600000001" not in lock


def test_a_status_is_queued_without_lock(tenants: Any) -> None:
    tenants(wa_tenant())
    assert post_wa(fixture("whatsapp/status_delivered.json")) == 200
    (event,) = events()
    assert (event.kind, event.status) == ("status", "pending")
    assert [(name, lock) for name, lock, _, _ in jobs()] == [("apply_status", None)]


def test_the_job_exists_only_if_the_event_is_committed(
    tenants: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    tenants(wa_tenant())

    def broken_defer(*args: object, **kwargs: object) -> None:
        raise ProcrastinateException("queue unavailable")

    with monkeypatch.context() as patch:
        patch.setattr(JobDeferrer, "defer", broken_defer)
        assert post_wa(fixture("whatsapp/text.json")) == 503
    assert events() == [] and jobs() == []
    assert post_wa(fixture("whatsapp/text.json")) == 200  # the provider's retry goes through
    assert len(events()) == 1 and len(jobs()) == 1


def test_a_duplicate_is_saved_and_queued_once(tenants: Any) -> None:
    tenants(wa_tenant())
    body = fixture("whatsapp/text.json")
    assert post_wa(body) == 200
    assert post_wa(body) == 200
    assert len(events()) == 1 and len(jobs()) == 1


def test_each_item_of_a_batch_is_its_own_event(tenants: Any) -> None:
    tenants(wa_tenant())
    assert post_wa(fixture("whatsapp/unsupported.json")) == 200
    assert len(events()) == 5 and len(jobs()) == 5


def test_rows_are_written_under_the_tenant(tenants: Any) -> None:
    tenants(wa_tenant(), wa_tenant("other"))
    post_wa(fixture("whatsapp/text.json"))
    other = get_registry().by_slug["other"]
    with tenant_tx(other.id):
        assert InboundEvent.objects.count() == 0
    with tenant_tx(get_registry().by_slug["wa"].id):
        assert InboundEvent.objects.count() == 1


# ── Ignored events ────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("changes", "status"),
    [
        ({"status": "paused"}, "ignored"),
        ({"config": {"colors": "not a list"}}, "pending"),  # degraded: the generic text
        ({"status": "onboarding", "testers": {"main": ["34999999999"]}}, "ignored"),
        ({"status": "onboarding", "testers": {"main": [BSUID]}}, "pending"),
        ({"status": "onboarding", "testers": {"main": ["34600000001"]}}, "pending"),  # by phone
        ({"status": "active", "testers": {}}, "pending"),
    ],
)
def test_main_channel_rules(tenants: Any, changes: dict[str, Any], status: str) -> None:
    tenants(wa_tenant(**changes))
    assert post_wa(fixture("whatsapp/text.json")) == 200
    (event,) = events()
    assert event.status == status
    assert len(jobs()) == (1 if status == "pending" else 0)


def test_statuses_are_applied_in_onboarding(tenants: Any) -> None:
    tenants(wa_tenant(status="onboarding", testers={"main": []}))
    post_wa(fixture("whatsapp/status_delivered.json"))
    assert [e.status for e in events()] == ["pending"]


def test_telegram_groups_are_ignored_without_saving(tenants: Any) -> None:
    tenants(tg_tenant())
    assert post_tg(fixture("telegram/group.json")) == 200
    assert events() == []


# ── GET verification ──────────────────────────────────────────────────────


def test_whatsapp_get_handshake(tenants: Any) -> None:
    tenants(wa_tenant())
    params = {
        "hub.mode": "subscribe",
        "hub.verify_token": WA_SECRETS["verify_token"],
        "hub.challenge": "1158201444",
    }
    response = Client().get(WA_URL, params)
    assert (response.status_code, response.content) == (200, b"1158201444")
    assert Client().get(WA_URL, {**params, "hub.verify_token": "nope"}).status_code == 403


# ── Database down ─────────────────────────────────────────────────────────


def test_database_errors_are_503(tenants: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    tenants(wa_tenant())

    def down(*args: object) -> int:
        raise OperationalError("connection refused")

    monkeypatch.setattr(views, "store", down)
    assert post_wa(fixture("whatsapp/text.json")) == 503


# ── /health and the Admin ─────────────────────────────────────────────────


def test_health(tenants: Any) -> None:
    # Public: only `status`, nothing a probe on the internet should learn. The tenant
    # detail is on /health/internal, which Caddy never forwards.
    tenants(wa_tenant(), wa_tenant("bad", config={"colors": 1}))
    response = Client().get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

    internal = Client().get("/health/internal")
    assert internal.status_code == 200
    assert internal.json() == {
        "status": "ok",
        "database": True,
        "tenants": {"loaded": 2, "degraded": 1, "unreadable": 0},
    }


def test_health_internal_is_hidden_behind_the_edge(tenants: Any) -> None:
    tenants()
    assert Client().get("/health/internal", headers={"X-Autobot-Edge": "public"}).status_code == 404
    assert Client().get("/health", headers={"X-Autobot-Edge": "public"}).status_code == 200


def test_health_without_database_is_503(tenants: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    tenants()

    class Broken:
        def cursor(self) -> None:
            raise OperationalError("down")

    monkeypatch.setattr("autobot.ops.views.connections", {"default": Broken()})
    # The public probe is liveness only (no database); the internal one reports it.
    assert Client().get("/health").status_code == 200
    assert Client().get("/health/internal").status_code == 503


def test_only_webhooks_and_health_are_public() -> None:
    from config import urls

    assert [str(p.pattern) for p in urls.public] == [
        "webhooks/whatsapp/<str:public_id>",
        "webhooks/telegram/<str:public_id>",
        "webhooks/telegram-demo",
        "webhooks/whatsapp-demo",
        "webhooks/telegram-notify",
        "health",
    ]
    # The panel API is mounted apart from `public`: Caddy's allowlist never reaches it
    # (PanelGateMiddleware gates it instead, by the X-Autobot-Edge header it adds).
    # /health/internal is also apart: Caddy's own `@public` matcher (deploy/caddy/
    # Caddyfile), separate from this list, never forwards it either.
    extra = [p for p in urls.urlpatterns if p not in urls.public]
    assert [str(p.pattern) for p in extra] == ["health/internal", "api/panel/"]
    assert Client().get("/admin/").status_code == 404


# ── Hardening ─────────────────────────────────────────────────────────────


def test_a_nul_in_a_signed_body_is_stored_clean_not_a_permanent_503(tenants: Any) -> None:
    tenants(wa_tenant())
    body = fixture("whatsapp/text.json").replace(b"Hola, quiero", b"Hola\\u0000, quiero")
    assert b"\\u0000" in body
    assert post_wa(body) == 200
    (event,) = events()
    assert "\\u0000" not in json.dumps(event.payload)


def test_a_data_error_is_dropped_with_200_but_a_connection_error_is_503(
    tenants: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    tenants(wa_tenant())

    def refuse(*args: object) -> None:
        raise DataError("unsupported Unicode escape sequence")

    monkeypatch.setattr(views, "accept", refuse)
    assert post_wa(fixture("whatsapp/text.json")) == 200

    def down(*args: object) -> None:
        raise OperationalError("connection refused")

    monkeypatch.setattr(views, "accept", down)
    assert post_wa(fixture("whatsapp/text.json")) == 503


def test_deeply_nested_json_is_400_not_500(tenants: Any) -> None:
    tenants(wa_tenant())
    assert post_wa(b"[" * 200_000) == 400


def test_the_body_limit_is_256_kb(tenants: Any) -> None:
    tenants(wa_tenant())
    assert views.MAX_BODY == 256 * 1024
    assert post_wa(b'{"x": "' + b"a" * (200 * 1024) + b'"}') == 200
