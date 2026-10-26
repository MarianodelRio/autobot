"""Health adapters use only mocked HTTP and never expose provider response text."""

from dataclasses import replace
from datetime import timedelta
from typing import Any

import httpx
import pytest
from django.db import connections
from django.utils import timezone

from core.pack import HealthIssue
from core.proactive import TemplateSpec
from flowpilot.ops import health
from flowpilot.tenancy.registry import get_registry
from tests.integration.helpers import wa_tenant

pytestmark = [
    pytest.mark.django_db(transaction=True, databases=["default", "owner"]),
    pytest.mark.usefixtures("clean_jobs"),
]


@pytest.fixture
def responses(monkeypatch: Any) -> Any:
    original = httpx.Client

    def setup(*answers: Any) -> list[httpx.Request]:
        queue = list(answers)
        requests = []

        def handler(request: httpx.Request) -> httpx.Response:
            assert not connections["default"].in_atomic_block
            requests.append(request)
            answer = queue.pop(0)
            if isinstance(answer, Exception):
                raise answer
            return httpx.Response(answer[0], json=answer[1])

        monkeypatch.setattr(
            httpx,
            "Client",
            lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs),
        )
        return requests

    return setup


@pytest.mark.parametrize(
    ("response", "code"),
    [
        ((200, {"ok": True, "result": {"url": "", "pending_update_count": 0}}), None),
        ((401, {"error_code": 401, "description": "secret token"}), "auth"),
        ((500, {"description": "secret token"}), "telegram_unavailable"),
        (
            (
                200,
                {
                    "ok": True,
                    "result": {"last_error_date": 9999999999, "last_error_message": "secret"},
                },
            ),
            "telegram_webhook",
        ),
        ((200, {"ok": True, "result": {"last_error_date": 1}}), None),
        ((200, {"ok": True, "result": None}), "telegram_response"),
    ],
)
def test_telegram(responses: Any, response: Any, code: str | None) -> None:
    requests = responses(response)
    issues = health.telegram_health("123456:token")
    assert [i.code for i in issues] == ([code] if code else [])
    assert "secret" not in str(issues)
    assert len(requests) == 1 and requests[0].url.path.endswith("/getWebhookInfo")


def test_outbound_only_bot_rejects_webhook(responses: Any) -> None:
    responses((200, {"ok": True, "result": {"url": "https://private.invalid/token"}}))
    assert health.telegram_health("token", outbound_only=True)[0].code == "notify_webhook"


@pytest.mark.parametrize(
    "response", [(401, {}), (400, {"error": {"code": 190, "message": "secret"}})]
)
def test_whatsapp_invalid_token(tenants: Any, responses: Any, response: Any) -> None:
    tenants(wa_tenant())
    responses(response)
    issues = call(get_registry().by_slug["wa"])
    assert issues[0].code == "auth" and "secret" not in str(issues)


def call(tenant: Any) -> list[Any]:
    """`whatsapp_health` as `tenant_health` calls it: the tenant's channel, secrets
    and its pack's templates."""
    templates = {(t.name, t.language) for t in tenant.pack.templates} if tenant.pack else set()
    return health.whatsapp_health(tenant.file.channel, tenant.secrets, templates)


def with_template() -> Any:
    tenant = get_registry().by_slug["wa"]
    assert tenant.pack
    object.__setattr__(
        tenant, "pack", replace(tenant.pack, templates=[TemplateSpec("notice", "es", "Hola", [])])
    )
    return tenant


@pytest.mark.parametrize(
    ("status", "language", "expected"),
    [("APPROVED", "es", []), ("PENDING", "es", ["templates"]), ("APPROVED", "en", ["templates"])],
)
def test_required_template_status_and_language(
    tenants: Any, responses: Any, status: str, language: str, expected: list[str]
) -> None:
    tenants(wa_tenant())
    tenant = with_template()
    requests = responses(
        (200, {"id": "number"}),
        (200, {"data": [{"name": "notice", "language": language, "status": status}]}),
    )
    assert [i.code for i in call(tenant)] == expected
    assert requests[0].headers["Authorization"].startswith("Bearer ")
    assert "access_token" not in str(requests[0].url)


def test_template_pagination_uses_fixed_host(tenants: Any, responses: Any) -> None:
    tenants(wa_tenant())
    tenant = with_template()
    requests = responses(
        (200, {}),
        (
            200,
            {
                "data": [],
                "paging": {
                    "next": "https://evil.invalid/?access_token=secret",
                    "cursors": {"after": "cursor"},
                },
            },
        ),
        (200, {"data": [{"name": "notice", "language": "es", "status": "APPROVED"}]}),
    )
    assert call(tenant) == []
    assert len(requests) == 3
    assert all(r.url.host == "graph.facebook.com" for r in requests)
    assert requests[-1].url.params["after"] == "cursor"


@pytest.mark.parametrize("answer", [httpx.ReadTimeout("secret"), (200, {"data": None})])
def test_health_failures_are_generic(tenants: Any, responses: Any, answer: Any) -> None:
    tenants(wa_tenant())
    tenant = with_template()
    responses((200, {}), answer)
    assert call(tenant)[0].code == "whatsapp_unavailable"


def test_pack_health_uses_context_and_sanitizes_messages(tenants: Any, monkeypatch: Any) -> None:
    tenants(wa_tenant())
    tenant = get_registry().by_slug["wa"]
    assert tenant.pack
    seen = []

    def failed_health(ctx: Any) -> list[HealthIssue]:
        seen.append(ctx)
        return [HealthIssue("calendar_unavailable", "private@example.org secret")]

    object.__setattr__(tenant, "pack", replace(tenant.pack, health=failed_health))
    monkeypatch.setattr(health, "whatsapp_health", lambda channel, secrets, templates: [])
    issues = health.tenant_health(tenant)
    assert len(seen) == 1 and seen[0].contact is None
    assert issues[0].severity == "🔴" and issues[0].code == "main:calendar_unavailable"
    assert "private" not in str(issues)


def test_cached_result_survives_day_deadline(tenants: Any, monkeypatch: Any) -> None:
    tenants()
    now = timezone.now()
    monkeypatch.setattr(timezone, "now", lambda: now)
    assert health.daily("test", lambda: [health.Issue("x", "Problema")])
    monkeypatch.setattr(timezone, "now", lambda: now + timedelta(days=2))
    with pytest.raises(RuntimeError):
        health.daily("test", lambda: (_ for _ in ()).throw(RuntimeError()))
    from django.core.cache import cache

    assert cache.get("health:test")["issues"][0].code == "x"
