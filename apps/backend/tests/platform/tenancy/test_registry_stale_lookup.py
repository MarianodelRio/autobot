"""A tenant written by another process is usable at once, without waiting for the
polling of this one (ADR-030). Reproduces the incident in which a just-imported tenant
was refused by the web, left pending by the inbound worker and not sent by the outbound
one: each held an old snapshot of the registry."""

import time
from types import SimpleNamespace
from typing import Any

import pytest
from django.test import Client
from django.utils import timezone

from autobot.runtime import process
from autobot.runtime.models import Contact, InboundEvent, OutboundMessage
from autobot.runtime.outbound import send_message
from autobot.tenancy import registry
from autobot.tenancy.models import Tenant
from core.replies import Text
from core.serialization import dump_outbound
from tests.helpers.integration import (
    WA_URL,
    Providers,
    post_wa,
    providers,  # noqa: F401
    tg_tenant,
    wa_tenant,
    wa_text,
)
from tests.platform.tenancy.helpers import WA_SECRETS, seed_db

pytestmark = [
    pytest.mark.django_db(transaction=True, databases=["default", "owner"]),
    pytest.mark.usefixtures("clean_jobs"),
]


@pytest.fixture
def stale(tenants: Any) -> SimpleNamespace:
    """This process loaded tenant A only; tenant B is then written, as a `tenant_config
    import` in another process would, and this process's registry is not reset."""
    tenants(tg_tenant())
    loaded = registry.get_registry()
    assert len(loaded.tenants) == 1
    old_revision = registry._revision
    document = wa_tenant()
    seed_db(document, secrets={"wa": WA_SECRETS}, reset=False)
    assert registry.loaded_registry() is loaded  # still the old snapshot
    return SimpleNamespace(document=document, snapshot=loaded, revision=old_revision)


def go_stale(stale: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> None:
    """Put the old snapshot (without B) back as the fresh cache of this process."""
    monkeypatch.setattr(registry, "_registry", stale.snapshot)
    monkeypatch.setattr(registry, "_revision", stale.revision)
    monkeypatch.setattr(registry, "_checked_at", time.monotonic())
    monkeypatch.setattr(registry, "_last_forced_at", float("-inf"))


def test_webhook_verification_and_post_of_a_new_tenant(stale: SimpleNamespace) -> None:
    response = Client().get(
        WA_URL,
        {
            "hub.mode": "subscribe",
            "hub.verify_token": WA_SECRETS["verify_token"],
            "hub.challenge": "1158201444",
        },
    )
    assert (response.status_code, response.content) == (200, b"1158201444")
    assert post_wa(wa_text("hola")) == 200


def test_process_event_of_a_new_tenant(
    stale: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert post_wa(wa_text("hola")) == 200
    event = InboundEvent.objects.using("owner").get()
    go_stale(stale, monkeypatch)  # the worker's snapshot, taken before B existed
    process.process_event(event.tenant_id, event.id, last_attempt=False)
    assert InboundEvent.objects.using("owner").get(id=event.id).status == "done"


def test_send_message_of_a_new_tenant(
    stale: SimpleNamespace,
    providers: Providers,  # noqa: F811 (the imported fixture)
) -> None:
    tenant = Tenant.objects.using("owner").get(pk=stale.document["id"])
    contact = Contact.objects.using("owner").create(
        tenant=tenant, channel="main", external_id="34600000001"
    )
    message = OutboundMessage.objects.using("owner").create(
        tenant=tenant,
        contact=contact,
        channel="main",
        kind="reply",
        idem_key="test:stale",
        payload=dump_outbound(Text("hola")),
        status="pending",
        created_at=timezone.now(),
    )
    send_message(tenant.id, message.pk)
    message.refresh_from_db(using="owner")
    assert message.status == "sent"
    assert len(providers.meta) == 1


def test_unknown_public_ids_cost_one_forced_check_per_window(
    tenants: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    tenants(tg_tenant())
    registry.get_registry()
    forced = []
    original = registry.get_registry

    def spy(*, force: bool = False) -> Any:
        if force:
            forced.append(1)
        return original(force=force)

    monkeypatch.setattr(registry, "get_registry", spy)
    client = Client()
    for i in range(50):
        assert client.get(f"/webhooks/whatsapp/unknown{i:04d}").status_code == 404
    assert len(forced) == 1
