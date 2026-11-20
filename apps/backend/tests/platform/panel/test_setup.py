"""The "Alta" tab's endpoints (ADR-014, C12): `GET .../setup` and
`POST .../setup/check/{step}`."""

import json
from typing import Any

import httpx
import pytest
from django.utils import timezone
from pytest_django import Settings

from autobot.ops import health
from autobot.ops.models import AuditEvent
from autobot.runtime.models import InboundEvent
from autobot.tenancy.registry import get_registry, source_from_dir
from packs.registry import PACKS as REGISTERED
from tests.helpers.integration import fixture, tg_tenant, wa_tenant
from tests.platform.panel.conftest import get, post
from tests.platform.tenancy.helpers import PACKS

pytestmark = [
    pytest.mark.django_db(transaction=True, databases=["default", "owner"]),
    pytest.mark.usefixtures("clean_jobs"),
]


@pytest.fixture(autouse=True)
def no_real_health_checks(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(health, "tenant_health", lambda tenant, **kw: [])


def salon_document(slug: str, **changes: Any) -> dict[str, Any]:
    template = REGISTERED["salon"].template
    assert template is not None
    config = source_from_dir(template).document["config"]
    doc = tg_tenant(slug, pack="salon", config=config)
    doc.update(changes)
    return doc


def test_setup_lists_the_common_and_channel_steps(authed_client: Any, tenants: Any) -> None:
    tenants(wa_tenant("a"))
    body = get(authed_client, "tenants/a/setup").json()
    keys = {step["key"] for step in body}
    assert {"document", "channel", "secrets", "templates", "health", "tester", "owner"} <= keys
    assert "webhook" not in keys  # WhatsApp has no webhook-registration step


def test_setup_includes_the_telegram_webhook_step(authed_client: Any, tenants: Any) -> None:
    tenants(tg_tenant("tg"))
    body = get(authed_client, "tenants/tg/setup").json()
    webhook = next(step for step in body if step["key"] == "webhook")
    assert webhook["checkable"] is True
    assert webhook["state"] == "pending"


def test_setup_includes_the_calendar_step_only_for_salon(
    authed_client: Any, tenants: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("packs.registry.PACKS", PACKS | REGISTERED)
    tenants(tg_tenant("tg"), salon_document("busi"))
    bus_steps = get(authed_client, "tenants/tg/setup").json()
    assert "calendar" not in {s["key"] for s in bus_steps}
    salon_steps = get(authed_client, "tenants/busi/setup").json()
    calendar = next(s for s in salon_steps if s["key"] == "calendar")
    assert calendar["checkable"] is True
    assert any(v["label"] == "Cuenta de servicio" for v in calendar["values"])


def test_check_webhook_reports_unregistered(
    authed_client: Any, tenants: Any, monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    tenants(tg_tenant("tg"))
    settings.PUBLIC_URL = "https://api.example.org"

    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": True, "result": {"url": ""}})

    original = httpx.Client
    monkeypatch.setattr(
        "httpx.Client", lambda **kwargs: original(transport=httpx.MockTransport(handle))
    )
    response = post(authed_client, "tenants/tg/setup/check/webhook")
    assert response.status_code == 200, response.content
    body = response.json()
    assert body["state"] == "error"
    assert AuditEvent.objects.using("owner").filter(action="tenant.setup_check").exists()


def test_check_calendar_without_credentials_is_a_clear_error(
    authed_client: Any, tenants: Any, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("packs.registry.PACKS", PACKS | REGISTERED)
    tenants(salon_document("busi"))
    settings.GOOGLE_SERVICE_ACCOUNT_FILE = ""
    response = post(authed_client, "tenants/busi/setup/check/calendar")
    assert response.status_code == 200, response.content
    body = response.json()
    assert body["state"] == "error"
    assert "secret" not in body["detail"].lower()


def test_check_an_uncheckable_step_is_rejected(authed_client: Any, tenants: Any) -> None:
    tenants(wa_tenant("a"))
    assert post(authed_client, "tenants/a/setup/check/document").status_code == 400


def test_check_an_unknown_step_is_rejected(authed_client: Any, tenants: Any) -> None:
    tenants(wa_tenant("a"))
    assert post(authed_client, "tenants/a/setup/check/nope").status_code == 400


def test_setup_includes_a_non_checkable_dataset_step_for_bus(
    authed_client: Any, tenants: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from autobot.tenancy import store

    monkeypatch.setattr("packs.registry.PACKS", PACKS | REGISTERED)
    template = source_from_dir(REGISTERED["bus"].template)  # type: ignore[arg-type]
    doc = tg_tenant("conbus", pack="bus", config=template.document["config"])
    tenants(doc)

    empty = get(authed_client, "tenants/conbus/setup").json()
    dataset_step = next(s for s in empty if s["key"] == "dataset:timetable")
    assert dataset_step["label"] == "Horarios"
    assert dataset_step["checkable"] is False
    assert dataset_step["state"] == "pending"

    store.import_dataset(
        "conbus",
        "timetable",
        template.datasets["timetable"],
        actor="op",
        comment="inicial",
        library_origin=None,
    )
    loaded = get(authed_client, "tenants/conbus/setup").json()
    loaded_step = next(s for s in loaded if s["key"] == "dataset:timetable")
    assert loaded_step["state"] == "ok"


# ── Testers (C12: "últimos que escribieron → añadir") ───────────────────────


def ignored_message(slug: str, chat_id: int) -> None:
    tenant = get_registry().by_slug[slug]
    body = json.loads(fixture("telegram/message.json"))
    body["update_id"] = chat_id
    body["message"]["from"]["id"] = chat_id
    body["message"]["chat"]["id"] = chat_id
    InboundEvent.objects.using("owner").create(
        tenant_id=tenant.id,
        channel="main",
        kind="message",
        provider_event_id=str(chat_id),
        payload=body,
        status=InboundEvent.Status.IGNORED,
        received_at=timezone.now(),
    )


def _tester_step(body: list[dict[str, Any]]) -> dict[str, Any]:
    return next(s for s in body if s["key"] == "tester")


def test_tester_candidates_list_recent_ignored_senders(authed_client: Any, tenants: Any) -> None:
    tenants(tg_tenant("tg", status="onboarding"))
    ignored_message("tg", 999)
    step = _tester_step(get(authed_client, "tenants/tg/setup").json())
    assert [c["id"] for c in step["tester_candidates"]] == ["999"]
    assert step["tester_candidates"][0]["display"] == "id 999"


def test_tester_candidates_exclude_an_existing_tester(authed_client: Any, tenants: Any) -> None:
    tenants(tg_tenant("tg", status="onboarding"))  # already has tester "100000001"
    ignored_message("tg", 100000001)
    step = _tester_step(get(authed_client, "tenants/tg/setup").json())
    assert step["tester_candidates"] == []


def test_add_tester_publishes_and_clears_the_candidate(authed_client: Any, tenants: Any) -> None:
    tenants(tg_tenant("tg", status="onboarding"))
    ignored_message("tg", 999)
    response = post(authed_client, "tenants/tg/setup/testers", {"id": "999"})
    assert response.status_code == 200, response.content
    step = response.json()
    assert step["key"] == "tester"
    assert step["tester_candidates"] == []
    assert "999" in get_registry(force=True).by_slug["tg"].document.testers.main
    assert AuditEvent.objects.using("owner").filter(action="tenant.setup_add_tester").exists()


def test_add_tester_twice_is_rejected(authed_client: Any, tenants: Any) -> None:
    tenants(tg_tenant("tg", status="onboarding"))
    assert post(authed_client, "tenants/tg/setup/testers", {"id": "100000001"}).status_code == 400


# ── WhatsApp templates (C12: texto y estado de cada plantilla) ─────────────


def salon_wa_document(slug: str, **changes: Any) -> dict[str, Any]:
    template = REGISTERED["salon"].template
    assert template is not None
    config = source_from_dir(template).document["config"]
    doc = wa_tenant(slug, pack="salon", config=config)
    doc.update(changes)
    return doc


def mock_graph(monkeypatch: pytest.MonkeyPatch, *answers: Any) -> None:
    queue = list(answers)
    original = httpx.Client

    def handle(request: httpx.Request) -> httpx.Response:
        status, body = queue.pop(0)
        return httpx.Response(status, json=body)

    monkeypatch.setattr(
        "httpx.Client", lambda **kw: original(transport=httpx.MockTransport(handle), **kw)
    )


def test_setup_shows_each_templates_text_before_checking(
    authed_client: Any, tenants: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("packs.registry.PACKS", PACKS | REGISTERED)
    tenants(salon_wa_document("busi"))
    step = next(
        s for s in get(authed_client, "tenants/busi/setup").json() if s["key"] == "templates"
    )
    assert step["checkable"] is True
    labels = {v["label"] for v in step["values"]}
    assert any("confirmacion_cita" in label and "sin comprobar" in label for label in labels)


def test_check_templates_reports_each_templates_status(
    authed_client: Any, tenants: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("packs.registry.PACKS", PACKS | REGISTERED)
    tenants(salon_wa_document("busi"))
    mock_graph(
        monkeypatch,
        (200, {"id": "number"}),
        (
            200,
            {
                "data": [
                    {"name": "confirmacion_cita", "language": "es_ES", "status": "APPROVED"},
                    {"name": "recordatorio_cita", "language": "es_ES", "status": "PENDING"},
                ]
            },
        ),
    )
    response = post(authed_client, "tenants/busi/setup/check/templates")
    assert response.status_code == 200, response.content
    body = response.json()
    assert body["state"] == "error"  # one is still pending
    labels = {v["label"] for v in body["values"]}
    assert any("confirmacion_cita" in label and "Aprobada" in label for label in labels)
    assert any("recordatorio_cita" in label and "Pendiente de Meta" in label for label in labels)


def test_check_templates_all_approved_is_ok(
    authed_client: Any, tenants: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("packs.registry.PACKS", PACKS | REGISTERED)
    tenants(salon_wa_document("busi"))
    mock_graph(
        monkeypatch,
        (200, {"id": "number"}),
        (
            200,
            {
                "data": [
                    {"name": "confirmacion_cita", "language": "es_ES", "status": "APPROVED"},
                    {"name": "recordatorio_cita", "language": "es_ES", "status": "APPROVED"},
                ]
            },
        ),
    )
    response = post(authed_client, "tenants/busi/setup/check/templates")
    assert response.json()["state"] == "ok"


def test_setup_includes_the_whatsapp_webhook_url(authed_client: Any, tenants: Any) -> None:
    tenants(wa_tenant("a"))
    step = next(s for s in get(authed_client, "tenants/a/setup").json() if s["key"] == "channel")
    assert any(
        "webhooks/whatsapp/puba0000" in v["value"]
        for v in step["values"]
        if "webhook" in v["label"].lower()
    )


# ── WhatsApp: acciones de alta por la Graph API (ADR-016, C18) ──────────────

WA_STEPS = ("whatsapp_webhook", "whatsapp_number", "whatsapp_subscription")


def graph(monkeypatch: pytest.MonkeyPatch, *answers: Any) -> list[httpx.Request]:
    """Each answer is a fixture name (200), a `(status, fixture name)` pair, or an
    exception to raise. Returns the requests Meta received."""
    queue = list(answers)
    seen: list[httpx.Request] = []
    original = httpx.Client

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        answer = queue.pop(0)
        if isinstance(answer, Exception):
            raise answer
        status, name = answer if isinstance(answer, tuple) else (200, answer)
        body = json.loads(fixture(f"whatsapp/{name}")) if name else {"success": True}
        return httpx.Response(status, json=body)

    monkeypatch.setattr(
        "httpx.Client", lambda **kw: original(transport=httpx.MockTransport(handle), **kw)
    )
    return seen


@pytest.fixture
def wa(tenants: Any, settings: Settings) -> str:
    settings.PUBLIC_URL = "https://api.example.org"
    tenants(wa_tenant("a"))
    return "a"


def step_of(client: Any, slug: str, key: str) -> dict[str, Any]:
    return next(s for s in get(client, f"tenants/{slug}/setup").json() if s["key"] == key)


def test_whatsapp_steps_offer_actions_without_calling_meta(
    authed_client: Any, wa: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen = graph(monkeypatch)
    body = get(authed_client, f"tenants/{wa}/setup").json()
    keys = [s["key"] for s in body]
    assert keys[keys.index("secrets") + 1 : keys.index("secrets") + 4] == list(WA_STEPS)
    steps = {s["key"]: s for s in body}
    assert all(steps[k]["state"] == "pending" and not steps[k]["blocking"] for k in WA_STEPS)
    assert steps["whatsapp_number"]["action"]["needs_pin"] is True
    assert steps["whatsapp_subscription"]["action"]["confirm"] is True
    assert steps["whatsapp_webhook"]["action"]["confirm"] is False
    assert seen == []


def test_whatsapp_steps_are_absent_for_telegram(authed_client: Any, tenants: Any) -> None:
    tenants(tg_tenant("tg"))
    keys = {s["key"] for s in get(authed_client, "tenants/tg/setup").json()}
    assert not keys & set(WA_STEPS)


def test_whatsapp_steps_without_ids_say_what_is_missing(authed_client: Any, tenants: Any) -> None:
    doc = wa_tenant("a")
    doc["channel"]["waba_id"] = None
    tenants(doc)
    step = step_of(authed_client, "a", "whatsapp_subscription")
    assert step["action"] is None
    assert "waba_id" in step["detail"]


def test_check_number_registered_is_ok_with_its_status(
    authed_client: Any, wa: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen = graph(monkeypatch, "graph_number_registered.json")
    body = post(authed_client, f"tenants/{wa}/setup/check/whatsapp_number").json()
    assert body["state"] == "ok"
    values = {v["label"]: v["value"] for v in body["values"]}
    assert values["Nombre visible"] == "APPROVED"
    assert values["Calidad"] == "GREEN"
    assert "600" not in json.dumps(body)  # never the phone number Meta reports
    assert "status,platform_type" in seen[0].url.params["fields"]
    assert seen[0].headers["Authorization"] == "Bearer EAAB-T0KEN"


def test_check_number_unregistered_is_an_error(
    authed_client: Any, wa: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    graph(monkeypatch, "graph_number_unregistered.json")
    body = post(authed_client, f"tenants/{wa}/setup/check/whatsapp_number").json()
    assert body["state"] == "error"
    assert "Registrar número" in body["detail"]


def test_check_subscription_ok_and_missing(
    authed_client: Any, wa: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    graph(monkeypatch, "graph_subscribed_apps.json", (200, ""))
    path = f"tenants/{wa}/setup/check/whatsapp_subscription"
    assert post(authed_client, path).json()["state"] == "ok"
    # `{"success": true}` has no `data`: an invalid answer, never a silent ok.
    assert post(authed_client, path).json()["state"] == "error"


def test_check_webhook_uses_the_app_token(
    authed_client: Any, wa: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen = graph(monkeypatch, "graph_app_subscriptions.json")
    body = post(authed_client, f"tenants/{wa}/setup/check/whatsapp_webhook").json()
    assert body["state"] == "ok"
    assert seen[0].url.path.endswith("/1/subscriptions")
    assert seen[0].headers["Authorization"] == "Bearer 1|" + "S3CR3T-APP-" + "x" * 21


def test_check_webhook_with_another_url_is_an_error(
    authed_client: Any, wa: str, monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    settings.PUBLIC_URL = "https://other.example.org"
    graph(monkeypatch, "graph_app_subscriptions.json")
    body = post(authed_client, f"tenants/{wa}/setup/check/whatsapp_webhook").json()
    assert body["state"] == "error"


def test_check_with_a_meta_error_does_not_echo_it(
    authed_client: Any, wa: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    graph(monkeypatch, (400, "graph_error.json"))
    body = post(authed_client, f"tenants/{wa}/setup/check/whatsapp_number").json()
    assert body["state"] == "error"
    assert "META-SECRET-DETAIL" not in json.dumps(body)


def test_register_skips_the_post_when_already_registered(
    authed_client: Any, wa: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen = graph(monkeypatch, "graph_number_registered.json")
    response = post(authed_client, f"tenants/{wa}/setup/action/whatsapp_number", {"pin": "123456"})
    assert response.status_code == 200, response.content
    assert "Ya estaba registrado" in response.json()["detail"]
    assert [r.method for r in seen] == ["GET"]
    event = AuditEvent.objects.using("owner").get(action="tenant.setup_action")
    assert event.details == {"step": "whatsapp_number", "outcome": "already"}


def test_register_posts_the_pin_and_never_audits_it(
    authed_client: Any, wa: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen = graph(monkeypatch, "graph_number_unregistered.json", (200, ""))
    response = post(authed_client, f"tenants/{wa}/setup/action/whatsapp_number", {"pin": "654321"})
    assert response.status_code == 200, response.content
    assert response.json()["state"] == "ok"
    assert seen[1].method == "POST"
    assert seen[1].url.path.endswith("/register")
    assert json.loads(seen[1].content) == {"messaging_product": "whatsapp", "pin": "654321"}
    event = AuditEvent.objects.using("owner").get(action="tenant.setup_action")
    assert "654321" not in json.dumps(event.details) + event.summary


@pytest.mark.parametrize("pin", ["12345", "1234567", "abcdef", "12 456", None])
def test_register_rejects_a_bad_pin_without_calling_meta(
    authed_client: Any, wa: str, monkeypatch: pytest.MonkeyPatch, pin: str | None
) -> None:
    seen = graph(monkeypatch)
    payload = {} if pin is None else {"pin": pin}
    response = post(authed_client, f"tenants/{wa}/setup/action/whatsapp_number", payload)
    assert response.status_code == 400
    assert seen == []


def test_an_ambiguous_write_is_unknown_and_not_retried(
    authed_client: Any, wa: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen = graph(monkeypatch, httpx.ReadTimeout("slow"))
    response = post(authed_client, f"tenants/{wa}/setup/action/whatsapp_subscription")
    assert response.status_code == 502
    assert "desconocido" in response.json()["message"]
    assert len(seen) == 1
    event = AuditEvent.objects.using("owner").get(action="tenant.setup_action")
    assert event.details == {"step": "whatsapp_subscription", "outcome": "unknown"}


def test_a_refused_write_does_not_echo_metas_body(
    authed_client: Any, wa: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    graph(monkeypatch, (400, "graph_error.json"))
    response = post(authed_client, f"tenants/{wa}/setup/action/whatsapp_webhook")
    assert response.status_code == 502
    text = response.content.decode()
    assert "META-SECRET-DETAIL" not in text and "fbtrace" not in text
    assert "tres secretos" in response.json()["message"]


def test_an_auth_error_says_the_token_has_no_access(
    authed_client: Any, wa: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    graph(monkeypatch, (401, "graph_error.json"))
    response = post(authed_client, f"tenants/{wa}/setup/action/whatsapp_subscription")
    assert response.status_code == 502
    assert "sin acceso" in response.json()["message"]


def test_subscribe_posts_to_the_waba(
    authed_client: Any, wa: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen = graph(monkeypatch, (200, ""))
    response = post(authed_client, f"tenants/{wa}/setup/action/whatsapp_subscription")
    assert response.status_code == 200, response.content
    assert seen[0].method == "POST"
    assert seen[0].url.path.endswith("/2/subscribed_apps")
    assert seen[0].headers["Authorization"] == "Bearer EAAB-T0KEN"


def test_configure_webhook_sends_the_url_verify_token_and_app_token(
    authed_client: Any, wa: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen = graph(monkeypatch, (200, ""))
    response = post(authed_client, f"tenants/{wa}/setup/action/whatsapp_webhook")
    assert response.status_code == 200, response.content
    request = seen[0]
    assert request.url.path.endswith("/1/subscriptions")
    assert request.headers["Authorization"].startswith("Bearer 1|S3CR3T-APP-")
    form = dict(httpx.QueryParams(request.content.decode()))
    assert form == {
        "object": "whatsapp_business_account",
        "callback_url": "https://api.example.org/webhooks/whatsapp/puba0000",
        "verify_token": "V3RIFY-T0KEN",
        "fields": "messages",
    }
    assert "V3RIFY" not in response.content.decode()


def test_configure_webhook_without_public_url_is_a_clear_error(
    authed_client: Any, wa: str, monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    settings.PUBLIC_URL = ""
    seen = graph(monkeypatch)
    response = post(authed_client, f"tenants/{wa}/setup/action/whatsapp_webhook")
    assert response.status_code == 502
    assert "PUBLIC_URL" in response.json()["message"]
    assert seen == []


def test_action_on_a_step_without_action_is_rejected(authed_client: Any, wa: str) -> None:
    assert post(authed_client, f"tenants/{wa}/setup/action/templates").status_code == 400
    assert post(authed_client, f"tenants/{wa}/setup/action/nope").status_code == 400


def test_action_rejects_a_telegram_tenant(authed_client: Any, tenants: Any) -> None:
    tenants(tg_tenant("tg"))
    response = post(authed_client, "tenants/tg/setup/action/whatsapp_subscription")
    assert response.status_code == 400
