"""Configuration mutations are versioned, serialized, validated and audited atomically."""

import copy
from typing import Any
from uuid import uuid7

import pytest
from django.utils import timezone

from autobot.ops.models import AuditEvent
from autobot.tenancy import activation, store
from autobot.tenancy.crypto import decrypt
from autobot.tenancy.models import (
    ConfigRevision,
    Tenant,
    TenantDatasetVersion,
    TenantDocumentVersion,
    TenantSecret,
)
from autobot.tenancy.registry import source_from_dir
from packs.registry import PACKS as REGISTERED
from tests.helpers.integration import tg_tenant
from tests.platform.tenancy.helpers import PACKS, TG_SECRETS

pytestmark = pytest.mark.django_db(transaction=True, databases=["default", "owner"])


@pytest.fixture(autouse=True)
def packs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("packs.registry.PACKS", PACKS | REGISTERED)


def create(doc: dict[str, Any] | None = None, **kwargs: Any) -> dict[str, Any]:
    doc = doc or tg_tenant()
    store.create_tenant(document=doc, actor="test", comment="Initial", **kwargs)
    return doc


def current(slug: str = "tg") -> TenantDocumentVersion:
    return TenantDocumentVersion.objects.using("owner").filter(tenant__slug=slug).latest("version")


def revision() -> int:
    return ConfigRevision.objects.using("owner").get(pk=1).revision


def test_create_publish_rollback_and_state() -> None:
    create()
    assert current().version == revision() == 1
    assert Tenant.objects.using("owner").get(slug="tg").status == "onboarding"
    doc = copy.deepcopy(current().document)
    doc["config"] = {"greeting": "Buenas"}
    assert store.publish("tg", document=doc, base_version=1, actor="user", comment="Greeting") == 2
    assert current().document["config"] == {"greeting": "Buenas"}
    assert revision() == 2
    with pytest.raises(store.StoreError) as conflict:
        store.publish("tg", document=doc, base_version=1, actor="user", comment="stale")
    assert conflict.value.code == "conflict" and revision() == 2
    assert store.rollback("tg", version=1, actor="user", comment="Undo") == 3
    assert current().document["config"] == {}
    events = list(AuditEvent.objects.using("owner").order_by("at"))
    assert [event.action for event in events] == [
        "tenant.create",
        "tenant.publish",
        "tenant.rollback",
    ]
    assert events[-1].details["version"] == revision() == 3


@pytest.mark.parametrize("path", store.IDENTITY)
def test_publish_protects_identity(path: tuple[str, ...]) -> None:
    create()
    doc = copy.deepcopy(current().document)
    if len(path) == 1:
        doc[path[0]] = {
            "id": str(uuid7()),
            "slug": "new-slug",
            "pack": "other",
            "status": "paused",
        }[path[0]]
    elif path[-1] == "type":
        doc["channel"] = {"type": "whatsapp", "public_id": doc["channel"]["public_id"]}
    else:
        doc["channel"]["public_id"] = "differentpublic"
    with pytest.raises(store.StoreError) as error:
        store.publish("tg", document=doc, base_version=1, actor="user", comment="Forbidden")
    assert error.value.code == "forbidden_change"
    assert current().version == revision() == 1


def test_validation_errors_do_not_echo_values() -> None:
    create()
    for changes, field in (
        ({"config": {"colors": "private-value"}}, "config.colors"),
        ({"timezone": "private-value"}, "timezone"),
    ):
        doc = current().document | changes
        with pytest.raises(store.StoreError) as error:
            store.publish("tg", document=doc, base_version=1, actor="user", comment="Bad")
        assert error.value.code == "validation_error"
        assert field in str(error.value.details)
        assert "private-value" not in str(error.value) + str(error.value.details)
    assert revision() == 1


def test_repeated_public_id_is_rejected_without_partial_rows() -> None:
    first = create()
    second = tg_tenant("second")
    second["channel"]["public_id"] = first["channel"]["public_id"]
    with pytest.raises(store.StoreError) as error:
        create(second)
    assert error.value.code == "validation_error"
    assert "public_id" in str(error.value.details)
    assert not Tenant.objects.using("owner").filter(slug="second").exists()
    assert revision() == 1


def test_existing_mirror_is_adopted_but_existing_versions_conflict() -> None:
    doc = tg_tenant()
    Tenant.objects.using("owner").create(
        id=doc["id"],
        slug=doc["slug"],
        name=doc["name"],
        pack=doc["pack"],
        status="active",
        timezone=doc["timezone"],
        synced_at=timezone.now(),
    )
    create(doc, keep_status=True)
    assert Tenant.objects.using("owner").get().status == "active"
    with pytest.raises(store.StoreError) as error:
        create(doc)
    assert error.value.code == "conflict"
    assert Tenant.objects.using("owner").count() == 1


def test_initial_secret_is_encrypted_and_audited_by_field_names() -> None:
    create(secrets=TG_SECRETS)
    secret = TenantSecret.objects.using("owner").get()
    assert decrypt(bytes(secret.ciphertext)) == TG_SECRETS
    event = AuditEvent.objects.using("owner").get(action="tenant.secrets")
    assert event.details == {"fields": sorted(TG_SECRETS)}
    assert not any(value in str(event.details) for value in TG_SECRETS.values())
    # Partial substitution: a field left out keeps its current, decrypted value.
    store.set_secrets("tg", secrets={"bot_token": "new-private"}, actor="user")
    secret.refresh_from_db(using="owner")
    assert decrypt(bytes(secret.ciphertext)) == {**TG_SECRETS, "bot_token": "new-private"}
    assert revision() == 2


def test_bus_creation_copies_template_dataset() -> None:
    pack = REGISTERED["bus"]
    assert pack.template is not None
    template = source_from_dir(pack.template)
    doc = tg_tenant("bus", pack="bus", config=template.document["config"])
    create(doc)
    rows = TenantDatasetVersion.objects.using("owner").filter(tenant__slug="bus")
    assert rows.count() == 1
    row = rows.get()
    assert row.name == "timetable" and row.files == template.datasets["timetable"]
    assert store.import_dataset("bus", "timetable", row.files, actor="user", comment="Same") is None
    assert revision() == 1
    with pytest.raises(store.StoreError) as error:
        store.import_dataset("bus", "timetable", {"../escape": "bad"}, actor="user", comment="Bad")
    assert error.value.code == "validation_error"
    assert revision() == 1 and rows.count() == 1
    files = dict(row.files)
    files["note.txt"] = "A harmless extra file"
    assert store.import_dataset("bus", "timetable", files, actor="user", comment="Note") == 2
    assert revision() == 2


def test_status_transitions_and_rollback_keep_current_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    create()
    with pytest.raises(store.StoreError):
        store.change_status("tg", action="activate", actor="user")
    monkeypatch.setattr(
        activation,
        "checklist",
        lambda slug: activation.Checklist([activation.Item("x", "x", False, True, "")]),
    )
    with pytest.raises(store.StoreError):
        store.change_status("tg", action="activate", confirm_slug="tg", actor="user")
    monkeypatch.setattr(activation, "checklist", lambda slug: activation.Checklist([]))
    assert store.change_status("tg", action="activate", confirm_slug="tg", actor="user") == 2
    assert store.change_status("tg", action="pause", actor="user") == 3
    assert store.rollback("tg", version=1, actor="user", comment="Keep paused") == 4
    assert current().document["status"] == "paused"
    assert store.change_status("tg", action="resume", actor="user") == 5
    with pytest.raises(store.StoreError):
        store.change_status("tg", action="offboard", actor="user")
    assert store.change_status("tg", action="offboard", confirm_slug="tg", actor="user") == 6
    assert current().document["status"] == "offboarded"
    with pytest.raises(store.StoreError) as error:
        store.change_status("tg", action="resume", actor="user")
    assert error.value.code == "invalid_status"
    assert revision() == 6


def test_pause_is_never_blocked_by_validation(monkeypatch: pytest.MonkeyPatch) -> None:
    """X10: a tenant degraded for a reason unrelated to pausing (or even a plain
    validation bug) must still be pausable — only "pause" skips revalidating the whole
    configuration; the other transitions still validate as before."""
    create()
    monkeypatch.setattr(activation, "checklist", lambda slug: activation.Checklist([]))
    store.change_status("tg", action="activate", confirm_slug="tg", actor="user")

    def boom(*args: Any, **kwargs: Any) -> None:
        raise store.StoreError("validation_error", "La configuración no es válida", [])

    monkeypatch.setattr(store, "_validate", boom)
    assert store.change_status("tg", action="pause", actor="user") == 3
    assert current().document["status"] == "paused"
    with pytest.raises(store.StoreError):
        store.change_status("tg", action="offboard", confirm_slug="tg", actor="user")


def test_demo_rejects_secrets_and_can_be_offboarded() -> None:
    doc = store.new_document(
        pack="toy",
        slug="demo",
        name="Demo",
        timezone="UTC",
        channel_type=None,
        demo_description="Try",
        config={},
    )
    create(doc)
    with pytest.raises(store.StoreError) as error:
        store.set_secrets("demo", secrets=TG_SECRETS, actor="user")
    assert error.value.code == "bad_request"
    store.change_status("demo", action="offboard", confirm_slug="demo", actor="user")
    assert current("demo").document["status"] == "offboarded"


def test_audit_failure_rolls_back_everything(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(**kwargs: Any) -> None:
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr(store, "record", fail)
    with pytest.raises(RuntimeError):
        create()
    assert not Tenant.objects.using("owner").exists()
    assert not TenantDocumentVersion.objects.using("owner").exists()
    assert revision() == 0


def test_new_documents_have_independent_ids_and_blank_channel_ids() -> None:
    args: Any = dict(
        pack="toy",
        slug="new",
        name="New",
        timezone="UTC",
        channel_type="whatsapp",
        demo_description=None,
        config={},
    )
    first, second = store.new_document(**args), store.new_document(**args)
    assert first["id"] != second["id"]
    assert first["channel"]["public_id"] != second["channel"]["public_id"]
    assert len(first["channel"]["public_id"]) == 16
    assert first["channel"]["phone_number_id"] is None
    assert first["status"] == "onboarding"


def test_slug_conflict_and_nontext_dataset_roll_back() -> None:
    create()
    with pytest.raises(store.StoreError) as error:
        create(tg_tenant())
    assert error.value.code == "conflict"
    with pytest.raises(store.StoreError) as error:
        store.import_dataset("tg", "rows", {"a": b"private-value"}, actor="user", comment="Bad")  # type: ignore[dict-item]
    assert error.value.code == "validation_error"
    assert "private-value" not in str(error.value.details)
    assert revision() == 1
