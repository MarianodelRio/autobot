"""Webhooks and /health (design.md §7.1, §13, §15.3, T-3.3): every branch of the entry,
against the real database. Transactional, because the tenant rows are written by
fp_owner and the webhook reads them as fp_app."""

import hashlib
import hmac
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from django.core.management import call_command
from django.db import OperationalError, connections
from django.test import Client
from procrastinate.exceptions import ProcrastinateException
from procrastinate.jobs import JobDeferrer
from pytest_django import Settings

from flowpilot.channels import views
from flowpilot.channels.ratelimit import InvalidSignatureLimiter
from flowpilot.runtime.locks import conversation_lock
from flowpilot.runtime.models import InboundEvent
from flowpilot.tenancy.registry import get_registry
from flowpilot.tenancy.tx import tenant_tx
from tests.tenancy.helpers import (
    PACKS,
    TG_SECRETS,
    WA_SECRETS,
    tenant_yaml,
    write_secrets,
    write_tenants,
)

pytestmark = pytest.mark.django_db(transaction=True, databases=["default", "owner"])

FIXTURES = Path(__file__).parent.parent / "fixtures"
PHONE_NUMBER_ID = "1122334455"  # the one in tests/fixtures/whatsapp
BSUID = "ES.13491208655302741918"
WA_URL = "/webhooks/whatsapp/pubwa0000"
TG_URL = "/webhooks/telegram/pubtg0000"


def wa_tenant(slug: str = "wa", **changes: Any) -> dict[str, Any]:
    doc = tenant_yaml(slug, **changes)
    doc["channel"] = {
        "type": "whatsapp",
        "public_id": f"pub{slug}0000",
        "app_id": "1",
        "waba_id": "2",
        "phone_number_id": PHONE_NUMBER_ID if slug == "wa" else str(len(slug) * 111),
    }
    return doc


def tg_tenant(slug: str = "tg", **changes: Any) -> dict[str, Any]:
    doc = tenant_yaml(slug, **changes)
    doc["channel"] = {"type": "telegram", "public_id": f"pub{slug}0000", "bot_username": "toy_bot"}
    doc["testers"] = {"main": ["100000001"]}
    return doc


@pytest.fixture
def tenants(tmp_path: Path, settings: Settings, monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    """Write tenants and secrets, load the registry and sync the tenant rows."""
    settings.TENANTS_DIR = tmp_path / "tenants"
    settings.SECRETS_FILE = tmp_path / "secrets.yaml"
    monkeypatch.setattr("packs.registry.PACKS", PACKS)
    monkeypatch.setattr(views, "limiter", InvalidSignatureLimiter())

    def setup(*docs: dict[str, Any], secrets: dict[str, Any] | None = None) -> None:
        write_tenants(tmp_path, *docs)
        default = {
            d["slug"]: WA_SECRETS if d["channel"]["type"] == "whatsapp" else TG_SECRETS
            for d in docs
        }
        write_secrets(tmp_path, default if secrets is None else secrets)
        get_registry.cache_clear()
        call_command("sync_tenants", stdout=None)

    yield setup
    get_registry.cache_clear()


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """A webhook never calls an external service (§7.1)."""

    def refuse(*args: object, **kwargs: object) -> None:
        raise AssertionError("the webhook made an external call")

    monkeypatch.setattr(httpx.Client, "send", refuse)


@pytest.fixture(autouse=True)
def clean_jobs() -> Iterator[None]:
    yield
    with connections["owner"].cursor() as cursor:
        cursor.execute("DELETE FROM procrastinate_jobs")


def fixture(path: str) -> bytes:
    return (FIXTURES / path).read_bytes()


def post_wa(body: bytes, secret: str = WA_SECRETS["app_secret"], ip: str = "203.0.113.1") -> int:
    signature = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    response = Client().post(
        WA_URL,
        data=body,
        content_type="application/json",
        headers={"X-Hub-Signature-256": signature},
        REMOTE_ADDR=ip,
    )
    return response.status_code


def post_tg(body: bytes, secret: str = TG_SECRETS["webhook_secret"], url: str = TG_URL) -> int:
    response = Client().post(
        url,
        data=body,
        content_type="application/json",
        headers={"X-Telegram-Bot-Api-Secret-Token": secret},
    )
    return response.status_code


def events() -> list[InboundEvent]:
    return list(InboundEvent.objects.using("owner").order_by("received_at"))


def jobs() -> list[tuple[str, str | None, dict[str, Any], str]]:
    with connections["owner"].cursor() as cursor:
        cursor.execute(
            "SELECT task_name, lock, args, queue_name FROM procrastinate_jobs ORDER BY id"
        )
        return [
            (n, lock, a if isinstance(a, dict) else json.loads(a), q)
            for n, lock, a, q in cursor.fetchall()
        ]


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
    assert post_wa(b'{"x": "' + b"a" * 64 * 1024 + b'"}') == 400
    assert events() == []


def test_invalid_json_is_400_after_the_signature(tenants: Any) -> None:
    tenants(wa_tenant())
    assert post_wa(b"not json") == 400
    assert post_wa(b"[1, 2]") == 400
    assert post_wa(b"not json", secret="wrong") == 401  # authenticity comes first


# ── 3. Authenticity and the IP limit ──────────────────────────────────────


def test_invalid_signatures_are_401_and_limited_per_ip(tenants: Any) -> None:
    tenants(wa_tenant())
    body = fixture("whatsapp/text.json")
    for _ in range(20):
        assert post_wa(body, secret="wrong") == 401
    assert post_wa(body) == 429  # even a valid one, from that IP
    assert post_wa(body, ip="198.51.100.7") == 200  # other IPs are not affected
    assert len(events()) == 1
    blocked = Client().post(
        "/webhooks/whatsapp/nobody000",
        data=b"{}",
        content_type="application/json",
        REMOTE_ADDR="203.0.113.1",
    )
    assert blocked.status_code == 429  # before looking up the tenant


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
        ({"config": {"colors": "not a list"}}, "ignored"),  # degraded
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
    tenants(wa_tenant(), wa_tenant("bad", config={"colors": 1}))
    response = Client().get("/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "database": True,
        "tenants": {"loaded": 2, "degraded": 1, "unreadable": 0},
    }


def test_health_without_database_is_503(tenants: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    tenants()

    class Broken:
        def cursor(self) -> None:
            raise OperationalError("down")

    monkeypatch.setattr("flowpilot.ops.views.connections", {"default": Broken()})
    response = Client().get("/health")
    assert response.status_code == 503
    assert response.json()["database"] is False


def test_admin_is_mounted_apart() -> None:
    from config import urls

    assert [str(p.pattern) for p in urls.public] == [
        "webhooks/whatsapp/<str:public_id>",
        "webhooks/telegram/<str:public_id>",
        "health",
    ]
    assert Client().get("/admin/").status_code == 302  # to its login
