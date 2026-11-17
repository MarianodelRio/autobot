"""The "Alta" tab's endpoints (ADR-014, C12): `GET .../setup` and
`POST .../setup/check/{step}`."""

from typing import Any

import httpx
import pytest
from pytest_django import Settings

from autobot.ops import health
from autobot.ops.models import AuditEvent
from autobot.tenancy.registry import source_from_dir
from packs.registry import PACKS as REGISTERED
from tests.helpers.integration import tg_tenant, wa_tenant
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
