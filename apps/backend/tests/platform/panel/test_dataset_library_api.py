"""The dataset library's panel endpoints (ADR-013, C21-C23)."""

from typing import Any

import pytest

from autobot.ops.models import AuditEvent
from autobot.tenancy import dataset_library
from autobot.tenancy.models import TenantDatasetVersion
from autobot.tenancy.registry import source_from_dir
from packs.registry import PACKS
from tests.helpers.integration import tg_tenant
from tests.platform.panel.conftest import get, post

pytestmark = pytest.mark.django_db(transaction=True, databases=["default", "owner"])


def bus_template() -> Any:
    template = PACKS["bus"].template
    assert template is not None
    return source_from_dir(template)


def bus_files() -> dict[str, str]:
    return dict(bus_template().datasets["timetable"])


def test_list_entries_is_empty_before_any_upload(authed_client: Any) -> None:
    response = get(authed_client, "packs/bus/datasets/timetable/library")
    assert response.status_code == 200
    assert response.json() == []


def test_list_entries_reports_the_summary_never_the_files(authed_client: Any) -> None:
    dataset_library.push(
        pack="bus",
        dataset="timetable",
        name="prueba",
        files=bus_files(),
        author="op",
        comment="c",
        base_sha=None,
    )
    response = get(authed_client, "packs/bus/datasets/timetable/library")
    assert response.status_code == 200
    (entry,) = response.json()
    assert entry["name"] == "prueba"
    assert entry["summary"]["pueblos"]
    assert "files" not in entry


def test_create_tenant_without_a_dataset_choice_is_rejected(authed_client: Any) -> None:
    template = bus_template()
    response = post(
        authed_client,
        "tenants",
        {
            "pack": "bus",
            "slug": "bus-sin-horarios",
            "name": "Bus sin horarios",
            "timezone": "Europe/Madrid",
            "channel_type": "telegram",
            "config": template.document["config"],
        },
    )
    assert response.status_code == 400, response.content


def test_create_tenant_with_a_dataset_choice_copies_from_the_library(
    authed_client: Any,
) -> None:
    dataset_library.push(
        pack="bus",
        dataset="timetable",
        name="prueba",
        files=bus_files(),
        author="op",
        comment="c",
        base_sha=None,
    )
    template = bus_template()
    response = post(
        authed_client,
        "tenants",
        {
            "pack": "bus",
            "slug": "bus-con-horarios",
            "name": "Bus con horarios",
            "timezone": "Europe/Madrid",
            "channel_type": "telegram",
            "config": template.document["config"],
            "dataset_choices": {"timetable": "prueba"},
        },
    )
    assert response.status_code == 200, response.content
    row = TenantDatasetVersion.objects.using("owner").get(tenant__slug="bus-con-horarios")
    assert row.source_name == "prueba" and row.source_version == 1


def test_create_tenant_with_an_unknown_dataset_choice_is_a_clear_422(
    authed_client: Any,
) -> None:
    template = bus_template()
    response = post(
        authed_client,
        "tenants",
        {
            "pack": "bus",
            "slug": "bus-malo",
            "name": "Bus malo",
            "timezone": "Europe/Madrid",
            "channel_type": "telegram",
            "config": template.document["config"],
            "dataset_choices": {"timetable": "no-existe"},
        },
    )
    assert response.status_code == 400, response.content
    assert "no-existe" not in response.content.decode()  # the id, not its content, is the issue


def test_apply_dataset_updates_an_existing_tenant_and_audits_it(
    authed_client: Any, tenants: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The shared `tenants` fixture narrows `packs.registry.PACKS` to the toy pack;
    # restore the real one so "bus" is still there.
    monkeypatch.setattr("packs.registry.PACKS", PACKS)
    v1 = dataset_library.push(
        pack="bus",
        dataset="timetable",
        name="prueba",
        files=bus_files(),
        author="op",
        comment="c",
        base_sha=None,
    )
    assert v1 is not None
    template = bus_template()
    doc = tg_tenant("busaplicar", pack="bus", config=template.document["config"])
    tenants(doc, secrets={"busaplicar": {"bot_token": "123:x", "webhook_secret": "w" * 32}})
    from autobot.tenancy import store

    store.import_dataset("busaplicar", "timetable", v1.files, actor="op", comment="inicial")
    changed = {**v1.files, "nota.txt": "cambio"}
    v2 = dataset_library.push(
        pack="bus",
        dataset="timetable",
        name="prueba",
        files=changed,
        author="op",
        comment="v2",
        base_sha=v1.sha256,
    )
    assert v2 is not None
    response = post(
        authed_client,
        "tenants/busaplicar/datasets/timetable/apply",
        {"name": "prueba"},
    )
    assert response.status_code == 200, response.content
    assert response.json()["version"] == 2  # v1 imported directly, v2 applied here
    assert AuditEvent.objects.using("owner").filter(action="dataset.import").exists()


def test_dataset_status_reports_the_origin_and_a_newer_version(
    authed_client: Any, tenants: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("packs.registry.PACKS", PACKS)
    v1 = dataset_library.push(
        pack="bus",
        dataset="timetable",
        name="prueba",
        files=bus_files(),
        author="op",
        comment="c",
        base_sha=None,
    )
    assert v1 is not None
    template = bus_template()
    doc = tg_tenant("busestado", pack="bus", config=template.document["config"])
    tenants(doc, secrets={"busestado": {"bot_token": "123:x", "webhook_secret": "w" * 32}})
    from autobot.tenancy import store

    store.import_dataset(
        "busestado",
        "timetable",
        v1.files,
        actor="op",
        comment="inicial",
        library_origin=dataset_library.origin(v1),
    )
    empty = get(authed_client, "tenants/busestado/datasets/schedule")
    assert empty.status_code == 200
    first = get(authed_client, "tenants/busestado/datasets/timetable")
    assert first.status_code == 200, first.content
    body = first.json()
    assert body["source_name"] == "prueba" and body["newer_version_available"] is None

    changed = {**v1.files, "nota.txt": "cambio"}
    v2 = dataset_library.push(
        pack="bus",
        dataset="timetable",
        name="prueba",
        files=changed,
        author="op",
        comment="v2",
        base_sha=v1.sha256,
    )
    assert v2 is not None
    second = get(authed_client, "tenants/busestado/datasets/timetable")
    assert second.json()["newer_version_available"] == 2
