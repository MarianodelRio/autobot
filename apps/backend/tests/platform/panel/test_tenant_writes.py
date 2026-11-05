"""Tenant mutations use the audited configuration store."""

import json
from typing import Any

import pytest

from autobot.ops.models import AuditEvent
from tests.helpers.integration import demo_tenant, wa_tenant
from tests.platform.panel.conftest import HOST, post
from tests.platform.tenancy.helpers import WA_SECRETS

pytestmark = pytest.mark.django_db(transaction=True, databases=["default", "owner"])


def put(client: Any, path: str, data: dict[str, Any]) -> Any:
    return client.put(
        f"/api/panel/{path}", data=json.dumps(data), content_type="application/json", HTTP_HOST=HOST
    )


def test_writes_and_audit(authed_client: Any, tenants: Any) -> None:
    doc = wa_tenant("a")
    tenants(doc)
    created = post(
        authed_client,
        "tenants",
        {
            "pack": "toy",
            "slug": "new",
            "name": "New",
            "timezone": "Europe/Madrid",
            "channel_type": "telegram",
            "config": {},
        },
    )
    assert created.status_code == 200, created.content
    doc["name"] = "Updated"
    published = put(
        authed_client, "tenants/a/document", {"document": doc, "base_version": 1, "comment": "edit"}
    )
    assert published.status_code == 200, published.content
    assert published.json()["version"] == 2
    assert (
        post(authed_client, "tenants/a/rollback", {"version": 1, "comment": "undo"}).status_code
        == 200
    )
    assert post(authed_client, "tenants/a/status", {"action": "pause"}).status_code == 200
    assert put(authed_client, "tenants/a/secrets", {"secrets": WA_SECRETS}).status_code == 204
    actions = set(
        AuditEvent.objects.using("owner").filter(actor="operator").values_list("action", flat=True)
    )
    assert {
        "tenant.create",
        "tenant.publish",
        "tenant.rollback",
        "tenant.status",
        "tenant.secrets",
    } <= actions


def test_rejections(authed_client: Any, tenants: Any) -> None:
    doc = wa_tenant("a")
    tenants(doc, demo_tenant("demo"))
    conflict = put(
        authed_client, "tenants/a/document", {"document": doc, "base_version": 999, "comment": ""}
    )
    assert conflict.status_code == 409
    assert post(authed_client, "tenants/a/status", {"action": "offboard"}).status_code == 400
    assert put(authed_client, "tenants/demo/secrets", {"secrets": WA_SECRETS}).status_code == 400
    doc["timezone"] = "sensitive-invalid-value"
    invalid = put(
        authed_client, "tenants/a/document", {"document": doc, "base_version": 1, "comment": ""}
    )
    assert invalid.status_code == 422
    assert invalid.json()["details"]
    assert "sensitive-invalid-value" not in invalid.content.decode()
