"""Exporting/forgetting a contact and exporting a business, from the panel
the panel equivalent of `contact_export`, `contact_forget` and
`tenant_data_export`, which stay CLI-only for a local file instead."""

from typing import Any

import pytest
from django.utils import timezone

from autobot.ops.models import AuditEvent
from autobot.runtime.models import Contact, InboundEvent, OutboundMessage
from autobot.tenancy.registry import get_registry
from tests.helpers.integration import wa_tenant
from tests.platform.panel.conftest import get, post, step_up

pytestmark = pytest.mark.django_db(transaction=True, databases=["default", "owner"])


@pytest.fixture
def authed_client(authed_client: Any, user: Any) -> Any:
    """These tests exercise actions that need a recent step-up (see test_stepup.py)."""
    assert step_up(authed_client, user).status_code == 200
    return authed_client


def tenant_id(slug: str) -> Any:
    return get_registry().by_slug[slug].id


def test_tenant_export_scopes_to_the_tenant_and_audits(authed_client: Any, tenants: Any) -> None:
    tenants(wa_tenant("a"), wa_tenant("b"))
    Contact.objects.using("owner").create(
        tenant_id=tenant_id("a"), channel="main", external_id="111", display_name="Ana"
    )
    Contact.objects.using("owner").create(
        tenant_id=tenant_id("b"), channel="main", external_id="222", display_name="Otro"
    )
    response = post(authed_client, "tenants/a/export")
    assert response.status_code == 200, response.content
    body = response.json()
    assert body["tenant"] == "a"
    contacts = body["data"]["contact"]
    assert [c["external_id"] for c in contacts] == ["111"]
    assert (
        AuditEvent.objects.using("owner")
        .filter(action="tenant.export", tenant_id=tenant_id("a"))
        .exists()
    )


def test_contact_export_scopes_to_one_contact_and_audits(authed_client: Any, tenants: Any) -> None:
    tenants(wa_tenant("a"))
    mine = Contact.objects.using("owner").create(
        tenant_id=tenant_id("a"), channel="main", external_id="111", display_name="Ana"
    )
    Contact.objects.using("owner").create(
        tenant_id=tenant_id("a"), channel="main", external_id="222", display_name="Otro"
    )
    response = get(authed_client, f"contacts/{mine.id}/export")
    assert response.status_code == 200, response.content
    body = response.json()
    contacts = body["data"]["contact"]
    assert [c["id"] for c in contacts] == [str(mine.id)]
    assert (
        AuditEvent.objects.using("owner")
        .filter(action="contact.export", target_id=str(mine.id))
        .exists()
    )


def test_contact_forget_deletes_the_contact_and_its_events(
    authed_client: Any, tenants: Any
) -> None:
    tenants(wa_tenant("a"))
    contact = Contact.objects.using("owner").create(
        tenant_id=tenant_id("a"), channel="main", external_id="111", display_name="Ana"
    )
    event = InboundEvent.objects.using("owner").create(
        tenant_id=tenant_id("a"),
        channel="main",
        kind="message",
        provider_event_id="1",
        payload={"message": {"from": {"id": "111"}}},
        status="done",
        received_at=timezone.now(),
    )
    OutboundMessage.objects.using("owner").create(
        tenant_id=tenant_id("a"),
        contact=contact,
        channel="main",
        kind="reply",
        idem_key="1",
        inbound_event=event,
        payload={"body": "Hola"},
        status="sent",
    )
    response = post(authed_client, f"contacts/{contact.id}/forget")
    assert response.status_code == 200, response.content
    assert not Contact.objects.using("owner").filter(pk=contact.id).exists()
    assert not InboundEvent.objects.using("owner").filter(pk=event.id).exists()
    assert (
        AuditEvent.objects.using("owner")
        .filter(action="contact.forget", target_id=str(contact.id))
        .exists()
    )


def test_contact_export_of_an_unknown_contact_is_404(authed_client: Any) -> None:
    import uuid

    assert get(authed_client, f"contacts/{uuid.uuid4()}/export").status_code == 404


def test_tenant_export_is_post_only_and_capped(
    authed_client: Any, tenants: Any, monkeypatch: Any
) -> None:
    from autobot.panel.services import tenants as tenant_service

    tenants(wa_tenant("a"))
    assert get(authed_client, "tenants/a/export").status_code == 405
    monkeypatch.setattr(tenant_service, "MAX_EXPORT_ROWS", -1)
    response = post(authed_client, "tenants/a/export")
    assert response.status_code == 413
    assert response.json()["code"] == "too_large"


def test_contact_list_and_search_are_audited_without_the_term(
    authed_client: Any, tenants: Any
) -> None:
    tenants(wa_tenant("a"))
    Contact.objects.using("owner").create(
        tenant_id=tenant_id("a"), channel="main", external_id="34600111222", display_name="Ana"
    )
    assert get(authed_client, "tenants/a/contacts").status_code == 200
    listed = AuditEvent.objects.using("owner").get(action="contact.list")
    assert listed.tenant_id == tenant_id("a")
    body = get(authed_client, "tenants/a/contacts?search=34600111222").json()
    assert [c["external_id"] for c in body["items"]] == ["34600111222"]
    searched = AuditEvent.objects.using("owner").get(action="contact.search")
    assert searched.details["search_length"] == 11
    assert len(searched.details["search_hmac"]) == 16
    dump = str(searched.details) + searched.summary + searched.actor + searched.target_id
    assert "34600111222" not in dump
    # Same term, same fingerprint; another term, another one.
    get(authed_client, "tenants/a/contacts?search=34600111222")
    get(authed_client, "tenants/a/contacts?search=Ana")
    fingerprints = [
        e.details["search_hmac"]
        for e in AuditEvent.objects.using("owner").filter(action="contact.search").order_by("at")
    ]
    assert fingerprints[0] == fingerprints[1] != fingerprints[2]
