"""A tenant written by another process is usable at once, without waiting for the
polling of this one (ADR-030). Reproduces the incident in which a just-imported tenant
was refused by the web, left pending by the inbound worker and not sent by the outbound
one: each held an old snapshot of the registry."""

import threading
import time
from types import SimpleNamespace
from typing import Any
from uuid import UUID

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
    for bucket in registry._buckets.values():
        monkeypatch.setattr(bucket, "last", float("-inf"))


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


def test_unknown_public_ids_cost_one_revision_read_per_window(
    tenants: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    tenants(tg_tenant())
    registry.get_registry()
    reads = []
    original = registry._read_revision

    def spy() -> int:
        reads.append(1)
        return original()

    monkeypatch.setattr(registry, "_read_revision", spy)
    client = Client()
    for i in range(50):
        assert client.get(f"/webhooks/whatsapp/unknown{i:04d}").status_code == 404
    assert len(reads) == 1


def test_a_lookup_inside_a_transaction_neither_waits_nor_rebuilds(
    stale: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`ops.actions._deliverable` resolves the tenant while it holds a row lock in an
    owner transaction: a miss there answers at once and leaves the rebuild to the
    refresher thread."""
    from django.db import transaction

    tenant_id = UUID(stale.document["id"])
    rebuilt_on = []
    original = registry._reload_locked

    def spy(now: float) -> Any:
        rebuilt_on.append(threading.current_thread().name)
        return original(now)

    monkeypatch.setattr(registry, "_reload_locked", spy)
    started = time.monotonic()
    with transaction.atomic(using="owner"):
        assert registry.tenant_by_id(tenant_id) is None
    assert time.monotonic() - started < 0.5
    assert "MainThread" not in rebuilt_on
    registry.wait_for_refresh()
    assert registry.tenant_by_id(tenant_id) is not None  # the refresher followed
