"""`tenants/*` read-only routes (DESIGN §6.4; T16a). Uses the `tenants` fixture
(`tests/integration/conftest.py`), which registers the `toy` pack."""

from datetime import UTC, datetime
from typing import Any
from uuid import uuid7

import pytest

from autobot.ops import health
from autobot.ops.models import OpsAlert
from autobot.runtime.models import Contact, InboundEvent, MetricEvent, Notification, OutboundMessage
from autobot.tenancy.models import TenantSecret
from autobot.tenancy.registry import get_registry
from tests.integration.helpers import demo_tenant, tg_tenant, wa_tenant
from tests.integration.panel.conftest import get, post
from tests.tenancy.helpers import WA_SECRETS

pytestmark = [
    pytest.mark.django_db(transaction=True, databases=["default", "owner"]),
    pytest.mark.usefixtures("clean_jobs"),
]

NOW = datetime(2026, 11, 4, 10, tzinfo=UTC)


@pytest.fixture(autouse=True)
def no_real_health_checks(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every route here but the health-check tests themselves must never reach a
    real provider (External network disabled in tests)."""
    monkeypatch.setattr(health, "tenant_health", lambda tenant, **kw: [])


def tenant_id(slug: str) -> Any:
    return get_registry().by_slug[slug].id


def metric(slug: str, kind: str, value: int, *, at: datetime = NOW) -> None:
    MetricEvent.objects.using("owner").create(
        tenant_id=tenant_id(slug), kind=kind, value=value, idem_key=str(uuid7())
    )


def test_list_tenants(authed_client: Any, tenants: Any) -> None:
    tenants(wa_tenant("a"))
    response = get(authed_client, "tenants")
    assert response.status_code == 200
    assert [row["slug"] for row in response.json()] == ["a"]


def test_slug_availability_includes_offboarded_and_unconfigured_tenants(
    authed_client: Any, tenants: Any
) -> None:
    from django.utils import timezone

    from autobot.tenancy.models import Tenant

    doc = wa_tenant("a")
    doc["status"] = "offboarded"
    tenants(doc)
    Tenant.objects.using("owner").create(
        id=uuid7(),
        slug="orphan",
        name="Orphan",
        pack="toy",
        status="onboarding",
        timezone="Europe/Madrid",
        synced_at=timezone.now(),
    )
    assert get(authed_client, "tenant-slug-availability?slug=a").json() == {"available": False}
    assert get(authed_client, "tenant-slug-availability?slug=orphan").json() == {"available": False}
    assert get(authed_client, "tenant-slug-availability?slug=free").json() == {"available": True}


def test_tenant_detail_whatsapp_channel(authed_client: Any, tenants: Any, settings: Any) -> None:
    settings.PUBLIC_URL = "https://example.test"
    doc = wa_tenant("a")
    doc["channel"]["display_phone"] = "+34 600 12 34 56"
    tenants(doc)
    body = get(authed_client, "tenants/a").json()
    assert body["channel_type"] == "whatsapp"
    assert (
        body["webhook_url"]
        == f"https://example.test/webhooks/whatsapp/{doc['channel']['public_id']}"
    )
    assert body["public_link"] == "https://wa.me/34600123456"
    assert body["owner_linked"] is False
    assert body["month"]["inbound"] == 0


def test_tenant_detail_only_includes_its_open_alerts(authed_client: Any, tenants: Any) -> None:
    tenants(wa_tenant("a"), wa_tenant("b"))
    OpsAlert.objects.using("owner").create(
        tenant_id=tenant_id("a"), kind="open", severity="warning", text="Aviso del cliente"
    )
    OpsAlert.objects.using("owner").create(
        tenant_id=tenant_id("b"), kind="other", severity="critical", text="Otro cliente"
    )
    OpsAlert.objects.using("owner").create(
        tenant_id=tenant_id("a"),
        kind="closed",
        severity="warning",
        text="Resuelta",
        resolved_at=NOW,
    )
    alerts = get(authed_client, "tenants/a").json()["open_alerts"]
    assert [alert["text"] for alert in alerts] == ["Aviso del cliente"]


def test_tenant_detail_telegram_with_bot_username(authed_client: Any, tenants: Any) -> None:
    tenants(tg_tenant("t"))  # tg_tenant already sets bot_username="toy_bot"
    body = get(authed_client, "tenants/t").json()
    assert body["channel_type"] == "telegram"
    assert body["public_link"] == "https://t.me/toy_bot"


def test_telegram_without_bot_username_has_no_public_link(authed_client: Any, tenants: Any) -> None:
    doc = tg_tenant("t")
    doc["channel"]["bot_username"] = None
    tenants(doc)
    body = get(authed_client, "tenants/t").json()
    assert body["public_link"] is None


def test_demo_tenant_detail_has_no_channel(authed_client: Any, tenants: Any) -> None:
    tenants(demo_tenant("demo-a"))
    body = get(authed_client, "tenants/demo-a").json()
    assert body["channel_type"] is None
    assert body["webhook_url"] is None
    assert body["public_link"] is None


def test_unknown_tenant_is_404(authed_client: Any, tenants: Any) -> None:
    tenants(wa_tenant("a"))
    assert get(authed_client, "tenants/nope").status_code == 404


def test_versions_and_version_detail(authed_client: Any, tenants: Any) -> None:
    tenants(wa_tenant("a"))
    versions = get(authed_client, "tenants/a/versions").json()
    assert len(versions) == 1 and versions[0]["version"] == 1
    detail = get(authed_client, "tenants/a/versions/1").json()
    assert detail["document"]["slug"] == "a"
    assert get(authed_client, "tenants/a/versions/2").status_code == 404


def test_secrets_status_never_leaks_the_value(authed_client: Any, tenants: Any) -> None:
    tenants(wa_tenant("a"))
    response = get(authed_client, "tenants/a/secrets")
    assert response.status_code == 200
    body = response.json()
    assert body["readable"] is True
    assert body["channel_type"] == "whatsapp"
    assert {f["name"] for f in body["fields"]} == {"app_secret", "access_token", "verify_token"}
    assert all(f["set"] for f in body["fields"])
    assert WA_SECRETS["app_secret"] not in response.content.decode()
    assert WA_SECRETS["access_token"] not in response.content.decode()


def test_secrets_status_when_unreadable(authed_client: Any, tenants: Any) -> None:
    tenants(wa_tenant("a"))
    row = TenantSecret.objects.using("owner").get(tenant_id=tenant_id("a"))
    row.ciphertext = b"not-a-valid-fernet-token"
    row.save(using="owner")
    body = get(authed_client, "tenants/a/secrets").json()
    assert body["readable"] is False
    assert all(not f["set"] for f in body["fields"])


def test_secrets_for_a_demo_tenant_is_bad_request(authed_client: Any, tenants: Any) -> None:
    tenants(demo_tenant("demo-a"))
    response = get(authed_client, "tenants/demo-a/secrets")
    assert response.status_code == 400


def test_activation_checklist(authed_client: Any, tenants: Any) -> None:
    tenants(wa_tenant("a"))
    body = get(authed_client, "tenants/a/activation-checklist").json()
    keys = {item["key"] for item in body}
    assert {"document", "channel", "secrets", "health", "tester", "owner"} <= keys


def test_notifications_are_isolated_per_tenant(authed_client: Any, tenants: Any) -> None:
    tenants(wa_tenant("a"), wa_tenant("b"))
    Notification.objects.using("owner").create(
        tenant_id=tenant_id("a"),
        idem_key="n1",
        audience=Notification.Audience.OWNER,
        kind="booking_created",
        text="Nueva cita",
    )
    Notification.objects.using("owner").create(
        tenant_id=tenant_id("b"),
        idem_key="n2",
        audience=Notification.Audience.OWNER,
        kind="booking_created",
        text="Cita de B, no debe verse en A",
    )
    body = get(authed_client, "tenants/a/notifications").json()
    assert [n["text"] for n in body] == ["Nueva cita"]


def test_health_check_forces_the_cache(authed_client: Any, tenants: Any, monkeypatch: Any) -> None:
    tenants(tg_tenant("t"))
    calls: list[int] = []

    def check(tenant: Any, **kw: Any) -> list[Any]:
        calls.append(1)
        return []

    monkeypatch.setattr(health, "tenant_health", check)
    response = post(authed_client, "tenants/t/health-check")
    assert response.status_code == 200
    assert response.json() == []
    assert calls == [1]  # forced, not read from the (empty) cache


def test_summary_of_tenant_a_never_counts_tenant_b(authed_client: Any, tenants: Any) -> None:
    """The A1 risk: `GET summary` must stay RLS-isolated per tenant."""
    tenants(wa_tenant("a"), wa_tenant("b"))
    metric("a", "greeted", 2)
    metric("b", "greeted", 100)
    InboundEvent.objects.using("owner").create(
        tenant_id=tenant_id("b"),
        channel="main",
        kind=InboundEvent.Kind.MESSAGE,
        provider_event_id=str(uuid7()),
        payload={},
        status=InboundEvent.Status.DONE,
        received_at=NOW,
    )
    contact_b = Contact.objects.using("owner").create(
        tenant_id=tenant_id("b"), channel="main", external_id="34600000099"
    )
    OutboundMessage.objects.using("owner").create(
        tenant_id=tenant_id("b"),
        contact=contact_b,
        channel="main",
        idem_key=str(uuid7()),
        kind=OutboundMessage.Kind.REPLY,
        payload={},
        status="sent",
        sent_at=NOW,
    )

    body = get(authed_client, "tenants/a/summary").json()
    assert body["pack_lines"] == [
        {"icon": "👋", "label": "Saludos", "value": "2.00", "unit": "count", "note": None}
    ]
    assert body["users"] == 0
    assert body["messages"] == 0
