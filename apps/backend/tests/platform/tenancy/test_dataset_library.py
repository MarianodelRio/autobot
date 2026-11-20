"""The dataset library (ADR-013): versioned, tenant-independent datasets, copied
(never referenced) into a tenant's own `TenantDatasetVersion`."""

from typing import Any

import pytest

from autobot.tenancy import dataset_library, store
from autobot.tenancy.registry import source_from_dir
from packs.registry import PACKS as REGISTERED
from tests.helpers.integration import tg_tenant
from tests.platform.tenancy.helpers import PACKS

pytestmark = pytest.mark.django_db(transaction=True, databases=["default", "owner"])

TOWNS = ["Posadas", "Córdoba"]


@pytest.fixture(autouse=True)
def packs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("packs.registry.PACKS", PACKS | REGISTERED)


def bus_template() -> Any:
    template = REGISTERED["bus"].template
    assert template is not None
    return source_from_dir(template)


def bus_files(town_count: int = 2) -> dict[str, str]:
    return dict(bus_template().datasets["timetable"])


def latest_version(pack: str, dataset: str, name: str) -> int:
    entry = dataset_library.latest(pack, dataset, name)
    assert entry is not None
    return entry.version


def test_push_creates_a_version_and_a_summary() -> None:
    entry = dataset_library.push(
        pack="bus",
        dataset="timetable",
        name="prueba",
        files=bus_files(),
        author="operator",
        comment="Primera subida",
        base_sha=None,
    )
    assert entry is not None
    assert entry.version == 1
    assert entry.summary["pueblos"]
    assert latest_version("bus", "timetable", "prueba") == 1


def test_push_is_a_noop_when_content_is_identical() -> None:
    files = bus_files()
    first = dataset_library.push(
        pack="bus",
        dataset="timetable",
        name="x",
        files=files,
        author="a",
        comment="1",
        base_sha=None,
    )
    assert first is not None
    again = dataset_library.push(
        pack="bus",
        dataset="timetable",
        name="x",
        files=files,
        author="a",
        comment="2",
        base_sha=first.sha256,
    )
    assert again is None
    assert latest_version("bus", "timetable", "x") == 1


def test_push_rejects_a_stale_base_sha() -> None:
    files = bus_files()
    first = dataset_library.push(
        pack="bus",
        dataset="timetable",
        name="y",
        files=files,
        author="a",
        comment="1",
        base_sha=None,
    )
    assert first is not None
    changed = {**files, "note.txt": "extra"}
    with pytest.raises(dataset_library.LibraryError):
        dataset_library.push(
            pack="bus",
            dataset="timetable",
            name="y",
            files=changed,
            author="a",
            comment="2",
            base_sha="not-the-real-sha",
        )
    assert latest_version("bus", "timetable", "y") == 1


def test_push_rejects_data_the_pack_cannot_validate() -> None:
    with pytest.raises(dataset_library.LibraryError):
        dataset_library.push(
            pack="bus",
            dataset="timetable",
            name="broken",
            files={"calendario.yaml": "{}"},
            author="a",
            comment="bad",
            base_sha=None,
        )
    assert dataset_library.latest("bus", "timetable", "broken") is None


def test_list_entries_reports_the_latest_version_of_each_name() -> None:
    files = bus_files()
    dataset_library.push(
        pack="bus",
        dataset="timetable",
        name="a",
        files=files,
        author="x",
        comment="",
        base_sha=None,
    )
    v1 = dataset_library.push(
        pack="bus",
        dataset="timetable",
        name="b",
        files=files,
        author="x",
        comment="",
        base_sha=None,
    )
    assert v1 is not None
    changed = {**files, "note.txt": "x"}
    dataset_library.push(
        pack="bus",
        dataset="timetable",
        name="b",
        files=changed,
        author="x",
        comment="v2",
        base_sha=v1.sha256,
    )
    entries = {e.name: e.version for e in dataset_library.list_entries("bus", "timetable")}
    assert entries == {"a": 1, "b": 2}


def test_create_tenant_requires_a_dataset_choice_for_bus() -> None:
    doc = tg_tenant("sindatos", pack="bus", config=REGISTERED["bus"].template)
    doc["config"] = {}
    # Build a minimal valid config via the template, the dataset choice is what's
    # actually under test here.
    template = bus_template()
    doc["config"] = template.document["config"]
    with pytest.raises(store.StoreError) as error:
        store.create_tenant(document=doc, actor="user", comment="x")
    assert error.value.code == "bad_request"


def test_create_tenant_with_a_library_choice_records_its_origin() -> None:
    from autobot.tenancy.models import TenantDatasetVersion

    files = bus_files()
    entry = dataset_library.push(
        pack="bus",
        dataset="timetable",
        name="origen",
        files=files,
        author="a",
        comment="",
        base_sha=None,
    )
    assert entry is not None
    template = bus_template()
    doc = tg_tenant("conorigen", pack="bus", config=template.document["config"])
    store.create_tenant(
        document=doc,
        datasets={"timetable": entry.files},
        dataset_origins={"timetable": dataset_library.origin(entry)},
        actor="user",
        comment="x",
    )
    row = TenantDatasetVersion.objects.using("owner").get(tenant__slug="conorigen")
    assert (row.source_name, row.source_version, row.source_sha) == (
        "origen",
        1,
        entry.sha256,
    )


def test_apply_to_tenant_copies_a_newer_version(settings: Any) -> None:
    from autobot.tenancy.models import TenantDatasetVersion

    files = bus_files()
    v1 = dataset_library.push(
        pack="bus",
        dataset="timetable",
        name="z",
        files=files,
        author="a",
        comment="",
        base_sha=None,
    )
    assert v1 is not None
    template = bus_template()
    doc = tg_tenant("clientez", pack="bus", config=template.document["config"])
    store.create_tenant(
        document=doc,
        datasets={"timetable": v1.files},
        dataset_origins={"timetable": dataset_library.origin(v1)},
        actor="user",
        comment="x",
    )
    changed = {**files, "note.txt": "cambio"}
    v2 = dataset_library.push(
        pack="bus",
        dataset="timetable",
        name="z",
        files=changed,
        author="a",
        comment="v2",
        base_sha=v1.sha256,
    )
    assert v2 is not None
    version = dataset_library.apply_to_tenant(
        "clientez", "timetable", pack="bus", name="z", version=None, actor="user", comment=""
    )
    assert version == 2
    row = TenantDatasetVersion.objects.using("owner").get(tenant__slug="clientez", version=2)
    assert (row.source_name, row.source_version) == ("z", 2)


def test_apply_to_tenant_reports_no_change_without_creating_a_version() -> None:

    files = bus_files()
    v1 = dataset_library.push(
        pack="bus",
        dataset="timetable",
        name="w",
        files=files,
        author="a",
        comment="",
        base_sha=None,
    )
    assert v1 is not None
    template = bus_template()
    doc = tg_tenant("clientew", pack="bus", config=template.document["config"])
    store.create_tenant(
        document=doc,
        datasets={"timetable": v1.files},
        dataset_origins={"timetable": dataset_library.origin(v1)},
        actor="user",
        comment="x",
    )
    result = dataset_library.apply_to_tenant(
        "clientew", "timetable", pack="bus", name="w", version=None, actor="user", comment=""
    )
    assert result is None


def test_push_race_on_the_unique_version_becomes_a_clean_library_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two uploads that both read the same `prior` must not surface a raw
    IntegrityError: the loser gets the same "bájala primero" error."""
    kwargs: dict[str, Any] = {
        "pack": "bus",
        "dataset": "timetable",
        "name": "carrera",
        "author": "operator",
        "comment": "x",
        "base_sha": None,
    }
    assert dataset_library.push(files=bus_files(), **kwargs) is not None
    monkeypatch.setattr(dataset_library, "latest", lambda *a, **k: None)  # a stale read
    changed = {**bus_files(), "note.txt": "other"}
    with pytest.raises(dataset_library.LibraryError, match="más reciente"):
        dataset_library.push(files=changed, **kwargs)
