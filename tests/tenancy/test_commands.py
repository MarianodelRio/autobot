"""sync_tenants and new_tenant (design.md §5.4, §16.1, T-2.4)."""

import io
from collections.abc import Iterator
from pathlib import Path

import pytest
import yaml
from django.core.management import CommandError, call_command
from pytest_django import Settings

from flowpilot.tenancy.models import Tenant
from flowpilot.tenancy.registry import get_registry, load_registry
from tests.tenancy.helpers import PACKS, tenant_yaml, write_tenants


@pytest.fixture
def tenants_dir(
    tmp_path: Path, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> Iterator[Path]:
    """A tenants/ directory of our own and the toy pack registered."""
    directory = tmp_path / "tenants"
    directory.mkdir()
    settings.TENANTS_DIR = directory
    settings.SECRETS_FILE = tmp_path / "secrets.yaml"
    monkeypatch.setattr("packs.registry.PACKS", PACKS)
    get_registry.cache_clear()
    yield directory
    get_registry.cache_clear()


def run(command: str, *args: str) -> tuple[str, str]:
    out, err = io.StringIO(), io.StringIO()
    call_command(command, *args, stdout=out, stderr=err)
    return out.getvalue(), err.getvalue()


@pytest.mark.django_db(databases=["default", "owner"])
def test_sync_tenants_is_idempotent(tenants_dir: Path) -> None:
    write_tenants(tenants_dir.parent, tenant_yaml("a"), tenant_yaml("b", status="onboarding"))
    out, _ = run("sync_tenants")
    assert "created a (active)" in out and "created b (onboarding)" in out
    first = {t.slug: (t.id, t.status, t.synced_at) for t in Tenant.objects.using("owner").all()}

    get_registry.cache_clear()
    out, _ = run("sync_tenants")
    assert "updated a" in out and "updated b" in out
    rows = Tenant.objects.using("owner").order_by("slug")
    assert [(t.slug, t.id, t.status) for t in rows] == [
        (s, v[0], v[1]) for s, v in sorted(first.items())
    ]


@pytest.mark.django_db(databases=["default", "owner"])
def test_sync_tenants_updates_changed_fields(tenants_dir: Path) -> None:
    doc = tenant_yaml("a")
    write_tenants(tenants_dir.parent, doc)
    run("sync_tenants")
    (tenants_dir / "a" / "tenant.yaml").write_text(
        yaml.safe_dump({**doc, "name": "Nuevo", "status": "paused"})
    )
    get_registry.cache_clear()
    run("sync_tenants")
    row = Tenant.objects.using("owner").get(slug="a")
    assert (row.name, row.status) == ("Nuevo", "paused")


@pytest.mark.django_db(databases=["default", "owner"])
def test_sync_tenants_keeps_going_with_broken_tenants(tenants_dir: Path) -> None:
    write_tenants(
        tenants_dir.parent,
        tenant_yaml("good"),
        tenant_yaml("deg", pack="nope"),
        raw={"bad": "id: ["},
    )
    out, err = run("sync_tenants")
    assert "created deg (degraded)" in out
    assert "skipped bad" in err
    assert set(Tenant.objects.using("owner").values_list("slug", flat=True)) == {"good", "deg"}


def test_new_tenant_creates_a_valid_onboarding_tenant(tenants_dir: Path) -> None:
    run("new_tenant", "nuevo-negocio", "--pack", "toy", "--channel", "whatsapp", "--name", "Nuevo")
    doc = yaml.safe_load((tenants_dir / "nuevo-negocio" / "tenant.yaml").read_text())
    registry = load_registry(tenants_dir, None, PACKS)
    (t,) = registry.tenants
    assert registry.problems == {}
    assert t.id.version == 7
    assert t.file.status == "onboarding" and t.file.name == "Nuevo"
    assert len(doc["channel"]["public_id"]) == 16
    assert t.main_disabled[0] == "whatsapp channel ids are missing"
    assert doc["config"] == {"greeting": "¡Hola!", "colors": ["Rojo", "Verde", "Azul"]}


def test_new_tenant_ids_are_unique(tenants_dir: Path) -> None:
    run("new_tenant", "uno", "--pack", "toy", "--channel", "telegram")
    run("new_tenant", "dos", "--pack", "toy", "--channel", "telegram")
    docs = [yaml.safe_load((tenants_dir / s / "tenant.yaml").read_text()) for s in ("uno", "dos")]
    assert docs[0]["id"] != docs[1]["id"]
    assert docs[0]["channel"]["public_id"] != docs[1]["channel"]["public_id"]
    assert load_registry(tenants_dir, None, PACKS).problems == {}


@pytest.mark.parametrize(
    ("args", "error"),
    [
        (["Mal_Slug", "--pack", "toy", "--channel", "whatsapp"], "Invalid slug"),
        (["x", "--pack", "nope", "--channel", "whatsapp"], "Unknown pack"),
    ],
)
def test_new_tenant_rejects_bad_input(tenants_dir: Path, args: list[str], error: str) -> None:
    with pytest.raises(CommandError, match=error):
        run("new_tenant", *args)


def test_new_tenant_never_overwrites(tenants_dir: Path) -> None:
    run("new_tenant", "uno", "--pack", "toy", "--channel", "whatsapp")
    with pytest.raises(CommandError, match="already exists"):
        run("new_tenant", "uno", "--pack", "toy", "--channel", "whatsapp")


@pytest.mark.django_db(databases=["default", "owner"])
def test_a_repeated_id_never_overwrites_the_other_tenant(tenants_dir: Path) -> None:
    original = tenant_yaml("dm-barber")
    write_tenants(tenants_dir.parent, original)
    run("sync_tenants")
    copy = tenant_yaml("copied", id=original["id"])  # copied directory, id not changed
    write_tenants(tenants_dir.parent, copy)
    get_registry.cache_clear()
    _, err = run("sync_tenants")
    assert "skipped copied: id repeated" in err and "skipped dm-barber: id repeated" in err
    row = Tenant.objects.using("owner").get()
    assert (row.slug, row.name) == ("dm-barber", "Dm-Barber")


@pytest.mark.django_db(databases=["default", "owner"])
def test_a_slug_taken_by_another_id_is_skipped(tenants_dir: Path) -> None:
    write_tenants(tenants_dir.parent, tenant_yaml("a"), tenant_yaml("b"))
    run("sync_tenants")
    (tenants_dir / "a" / "tenant.yaml").write_text(yaml.safe_dump(tenant_yaml("a")))  # new id
    get_registry.cache_clear()
    out, err = run("sync_tenants")
    assert "skipped a: its slug belongs to another tenant id" in err
    assert "updated b" in out


def test_config_skeleton_dumps_complex_defaults() -> None:
    from datetime import time
    from decimal import Decimal

    from pydantic import BaseModel

    from flowpilot.management.commands.new_tenant import config_skeleton

    class Item(BaseModel):
        at: time = time(9, 30)

    class Config(BaseModel):
        required: str
        price: Decimal = Decimal("9.50")
        items: list[Item] = [Item()]

    skeleton = config_skeleton(Config)
    assert skeleton == {"required": None, "price": "9.50", "items": [{"at": "09:30:00"}]}
    yaml.safe_dump(skeleton)  # YAML-friendly
