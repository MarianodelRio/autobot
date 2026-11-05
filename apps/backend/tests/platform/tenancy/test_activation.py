"""Activation checks run outside transactions and require main-channel activity."""

from typing import Any
from uuid import uuid7

import pytest
from django.db import connections
from django.utils import timezone

from autobot.ops import health
from autobot.runtime.models import InboundEvent, OwnerLink
from autobot.tenancy import activation, store
from tests.helpers.integration import tg_tenant, wa_tenant
from tests.platform.tenancy.helpers import PACKS, TG_SECRETS, WA_SECRETS

pytestmark = pytest.mark.django_db(transaction=True, databases=["default", "owner"])


@pytest.fixture(autouse=True)
def packs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("packs.registry.PACKS", PACKS)


def create(doc: dict[str, Any], secrets: dict[str, str]) -> None:
    store.create_tenant(document=doc, secrets=secrets, actor="test", comment="Initial")


def inbound(doc: dict[str, Any], channel: str = "main") -> None:
    InboundEvent.objects.using("owner").create(
        tenant_id=doc["id"],
        id=uuid7(),
        channel=channel,
        provider_event_id=str(uuid7()),
        kind="message",
        payload={},
        received_at=timezone.now(),
    )


def test_checklist_and_activation_have_no_external_transaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    doc = tg_tenant()
    create(doc, TG_SECRETS)
    calls = []

    def check(tenant: Any) -> list[health.Issue]:
        assert not connections["owner"].in_atomic_block
        assert not connections["default"].in_atomic_block
        calls.append(tenant.id)
        return []

    monkeypatch.setattr(health, "tenant_health", check)
    result = activation.checklist("tg")
    assert result.blocking == ["tester"]
    inbound(doc, "demo_tg")
    assert activation.checklist("tg").blocking == ["tester"]
    inbound(doc)
    result = activation.checklist("tg")
    assert result.blocking == []
    assert not next(item for item in result.items if item.key == "owner").ok
    OwnerLink.objects.using("owner").create(tenant_id=doc["id"], chat_id=123)
    assert all(item.ok for item in activation.checklist("tg").items)
    assert store.change_status("tg", action="activate", actor="user", confirm_slug="tg") == 2
    assert len(calls) == 5


def test_whatsapp_templates_and_red_health_block(monkeypatch: pytest.MonkeyPatch) -> None:
    doc = wa_tenant()
    create(doc, WA_SECRETS)
    inbound(doc)
    monkeypatch.setattr(
        health, "tenant_health", lambda tenant: [health.Issue("templates", "Missing")]
    )
    assert activation.checklist("wa").blocking == ["templates"]
    monkeypatch.setattr(
        health, "tenant_health", lambda tenant: [health.Issue("auth", "Denied", "🔴")]
    )
    assert activation.checklist("wa").blocking == ["health"]
    with pytest.raises(store.StoreError):
        store.change_status("wa", action="activate", actor="user", confirm_slug="wa")


def test_activation_rechecks_state_after_provider_call(monkeypatch: pytest.MonkeyPatch) -> None:
    doc = tg_tenant()
    create(doc, TG_SECRETS)
    inbound(doc)

    def check(tenant: Any) -> list[health.Issue]:
        store.change_status("tg", action="offboard", actor="other", confirm_slug="tg")
        return []

    monkeypatch.setattr(health, "tenant_health", check)
    with pytest.raises(store.StoreError) as error:
        store.change_status("tg", action="activate", actor="user", confirm_slug="tg")
    assert error.value.code == "invalid_status"
