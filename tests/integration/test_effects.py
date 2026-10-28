"""Authorization survives an external effect but stays bound to its exact scope."""

import uuid
from typing import Any

import pytest
from django.utils import timezone

from autobot.runtime.effects import StoredEffects
from autobot.runtime.models import InboundEvent
from autobot.tenancy.tx import tenant_tx
from core.errors import PermanentError

pytestmark = pytest.mark.django_db(transaction=True, databases=["default", "owner"])


def test_effect_journal_scope_and_conflicts(salon_setup: Any) -> None:
    setup, _ = salon_setup
    tenant = setup()
    with tenant_tx(tenant.id):
        event = InboundEvent.objects.create(
            tenant_id=tenant.id,
            channel="main",
            kind="message",
            provider_event_id="effects",
            payload={},
            status="pending",
            received_at=timezone.now(),
        )
    contact = uuid.uuid7()
    store = StoredEffects(tenant.id, event.id, contact, "main", "calendar")
    store.put("cancel:one", {"target": "one"})
    assert store.get("cancel:one") == {"target": "one"}
    assert event.payload == {}
    assert (
        StoredEffects(tenant.id, event.id, uuid.uuid7(), "main", "calendar").get("cancel:one")
        is None
    )
    assert (
        StoredEffects(tenant.id, event.id, contact, "main", "other-calendar").get("cancel:one")
        is None
    )
    with pytest.raises(PermanentError, match="Conflicting"):
        store.put("cancel:one", {"target": "other"})
    with tenant_tx(tenant.id):
        InboundEvent.objects.filter(id=event.id).update(status="done")
    with pytest.raises(PermanentError):
        store.put("cancel:two", {"target": "two"})


def test_journal_cannot_be_read_through_another_tenant(salon_setup: Any) -> None:
    setup, _ = salon_setup
    tenant = setup()
    with tenant_tx(tenant.id):
        event = InboundEvent.objects.create(
            tenant_id=tenant.id,
            channel="main",
            kind="message",
            provider_event_id="scope",
            payload={},
            status="pending",
            received_at=timezone.now(),
        )
    contact = uuid.uuid7()
    StoredEffects(tenant.id, event.id, contact, "main", "calendar").put("cancel", {"target": "one"})
    with pytest.raises(InboundEvent.DoesNotExist):
        StoredEffects(uuid.uuid7(), event.id, contact, "main", "calendar").get("cancel")
    with pytest.raises(PermanentError):
        StoredEffects(tenant.id, event.id, contact, "test", "calendar").get("cancel")
