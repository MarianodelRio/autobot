"""The incremental reload (ADR-030) builds exactly the registry a full load would, and
loads only the tenants that changed."""

import random
import uuid
from typing import Any

import pytest
from django.db import connections
from django.utils import timezone

from autobot.tenancy import registry
from autobot.tenancy.crypto import encrypt
from autobot.tenancy.models import (
    ConfigRevision,
    Tenant,
    TenantDatasetVersion,
    TenantDocumentVersion,
    TenantSecret,
)
from tests.platform.tenancy.helpers import (
    PACKS,
    TG_SECRETS,
    WA_SECRETS,
    demo_tenant_yaml,
    tenant_document,
)

pytestmark = pytest.mark.django_db(transaction=True, databases=["default", "owner"])

SLUGS = ["alpha", "beta", "gamma", "delta"]
PUBLIC_IDS = ["pubalpha0000", "pubbeta00000", "pubgamma0000"]
PHONES = ["111", "222", "333"]


@pytest.fixture(autouse=True)
def packs(monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.setattr("packs.registry.PACKS", PACKS)
    registry.reset_registry()
    yield
    registry.reset_registry()


class Writer:
    """Writes configuration the way the store does (new document version, new dataset
    version, secrets upsert, a revision bump), plus what the store never does: a purge."""

    def __init__(self) -> None:
        self.ids = [uuid.uuid7() for _ in range(6)]
        self.created: set[int] = set()

    def bump(self) -> None:
        revision, _ = ConfigRevision.objects.using("owner").get_or_create(pk=1)
        revision.revision += 1
        revision.save(using="owner")

    def document(self, slot: int, rng: random.Random) -> dict[str, Any]:
        kind = rng.choice(["wa", "wa", "wa", "tg", "demo", "invalid", "config", "pack"])
        slug = rng.choice(SLUGS)
        tenant_id = self.ids[slot] if rng.random() > 0.1 else rng.choice(self.ids)
        base = tenant_document(slug, id=str(tenant_id))
        base["channel"]["public_id"] = rng.choice(PUBLIC_IDS)
        base["channel"]["phone_number_id"] = rng.choice(PHONES)
        base["name"] = f"{slug}-{rng.randrange(1000)}"
        if kind == "tg":
            base["channel"] = {
                "type": "telegram",
                "public_id": rng.choice(PUBLIC_IDS),
                "bot_username": "toy_bot",
            }
        elif kind == "demo":
            base = demo_tenant_yaml(slug, id=str(tenant_id))
        elif kind == "invalid":
            del base["name"]
        elif kind == "config":
            base["config"] = {"colors": 5}
        elif kind == "pack":
            base["pack"] = "nope"
        return base

    def write_document(self, slot: int, doc: dict[str, Any]) -> None:
        tenant, _ = Tenant.objects.using("owner").update_or_create(
            pk=self.ids[slot],
            defaults={
                "slug": f"slot{slot}",
                "name": "n",
                "pack": "toy",
                "status": "active",
                "timezone": "Europe/Madrid",
                "synced_at": timezone.now(),
            },
        )
        last = (
            TenantDocumentVersion.objects.using("owner")
            .filter(tenant=tenant)
            .order_by("-version")
            .first()
        )
        TenantDocumentVersion.objects.using("owner").create(
            tenant=tenant,
            version=last.version + 1 if last else 1,
            document=doc,
            author="test",
            comment="",
        )
        self.created.add(slot)

    def write_dataset(self, slot: int, rng: random.Random) -> None:
        name = rng.choice(["rows", "timetable", "../bad"])
        files = {"a.csv": str(rng.randrange(100))}
        if rng.random() < 0.2:
            files = {"../escape.csv": "x"}
        last = (
            TenantDatasetVersion.objects.using("owner")
            .filter(tenant_id=self.ids[slot], name=name)
            .order_by("-version")
            .first()
        )
        TenantDatasetVersion.objects.using("owner").create(
            tenant_id=self.ids[slot],
            name=name,
            version=last.version + 1 if last else 1,
            files=files,
            sha256="0" * 64,
            author="test",
            comment="",
        )

    def write_secrets(self, slot: int, rng: random.Random) -> None:
        wa = rng.random() < 0.7
        raw: Any = WA_SECRETS if wa else TG_SECRETS
        if rng.random() < 0.2:
            raw = {"bot_token": "x"}  # invalid for either schema
        ciphertext = encrypt(raw)
        if rng.random() < 0.1:
            ciphertext = b"corrupt"
        TenantSecret.objects.using("owner").update_or_create(
            tenant_id=self.ids[slot],
            defaults={
                "channel_type": "whatsapp" if wa else "telegram",
                "ciphertext": ciphertext,
                "updated_by": "test",
            },
        )

    def purge(self, slot: int, rng: random.Random) -> None:
        what = rng.choice(["tenant", "secrets", "datasets"])
        if what == "tenant":
            Tenant.objects.using("owner").filter(pk=self.ids[slot]).delete()
            self.created.discard(slot)
        elif what == "secrets":
            TenantSecret.objects.using("owner").filter(tenant_id=self.ids[slot]).delete()
        else:
            TenantDatasetVersion.objects.using("owner").filter(tenant_id=self.ids[slot]).delete()

    def step(self, rng: random.Random) -> None:
        for _ in range(rng.choice([1, 1, 2, 3])):
            slot = rng.randrange(len(self.ids))
            action = rng.choice(["doc", "doc", "doc", "dataset", "secrets", "secrets", "purge"])
            if action == "doc":
                self.write_document(slot, self.document(slot, rng))
            elif slot in self.created and action == "dataset":
                self.write_dataset(slot, rng)
            elif slot in self.created and action == "secrets":
                self.write_secrets(slot, rng)
            elif slot in self.created and action == "purge":
                self.purge(slot, rng)
        self.bump()


def shape(r: registry.Registry) -> dict[str, Any]:
    return {
        "tenants": r.tenants,
        "errors": r.errors,
        "problems": r.problems,
        "by_id": r.by_id,
        "by_slug": r.by_slug,
        "by_public_id": r.by_public_id,
        "by_phone_number_id": r.by_phone_number_id,
        "main_disabled": [(t.slug, t.main_disabled) for t in r.tenants],
        "degraded": [(t.slug, t.degraded, t.ambiguous) for t in r.tenants],
    }


def full_registry() -> registry.Registry:
    _, sources = registry.sources_from_database()
    return registry.load_registry(sources, PACKS)


@pytest.mark.parametrize("seed", range(30))
def test_incremental_equals_a_full_load_after_random_writes(
    seed: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    rng = random.Random(seed)
    writer = Writer()
    writer.bump()
    original = registry._read_entries
    reads: list[bool] = []

    def spy(previous: Any, packs: Any) -> Any:
        reads.append(previous is not None)
        return original(previous, packs)

    monkeypatch.setattr(registry, "_read_entries", spy)
    registry.get_registry(force=True)
    for _ in range(12):
        writer.step(rng)
        incremental = registry.get_registry(force=True)
        assert shape(incremental) == shape(full_registry())
    # Every round after the first was incremental, never a silent full rebuild.
    assert reads == [False] + [True] * 12
    degraded = [t for t in incremental.tenants if t.degraded]
    # Cached tenants carry no mark of the cross-tenant passes of earlier rounds: a
    # tenant that stopped being a duplicate is healthy again (checked by the equality
    # above on every step), and none accumulates the same reason twice.
    for t in degraded:
        assert len(t.degraded) == len(set(t.degraded))
    connections.close_all()


def test_the_loaded_snapshots_are_not_mutated_by_later_rounds() -> None:
    """A pinned snapshot (a job's scope) keeps what it had after the next reload."""
    writer = Writer()
    docs = [
        tenant_document("alpha", id=str(writer.ids[0])),
        tenant_document("beta", id=str(writer.ids[1])),
    ]
    docs[1]["channel"]["public_id"] = docs[0]["channel"]["public_id"]  # a duplicate
    for slot, doc in enumerate(docs):
        writer.write_document(slot, doc)
    writer.bump()
    first = registry.get_registry(force=True)
    before = shape(first)
    assert all(t.ambiguous for t in first.tenants)
    docs[1]["channel"]["public_id"] = "pubbeta00000"
    writer.write_document(1, docs[1])
    writer.bump()
    second = registry.get_registry(force=True)
    assert not any(t.ambiguous or t.degraded for t in second.tenants)
    assert shape(first) == before


def test_an_unchanged_tenant_is_not_loaded_again(monkeypatch: pytest.MonkeyPatch) -> None:
    writer = Writer()
    for slot, slug in enumerate(["alpha", "beta", "gamma"]):
        writer.write_document(slot, tenant_document(slug, id=str(writer.ids[slot])))
    writer.bump()
    loaded: list[str] = []
    original = registry._load_tenant

    def spy(source: registry.TenantSource, packs: Any) -> Any:
        loaded.append(source.name)
        return original(source, packs)

    monkeypatch.setattr(registry, "_load_tenant", spy)
    first = registry.get_registry(force=True)
    assert sorted(loaded) == ["alpha", "beta", "gamma"]
    loaded.clear()

    writer.write_document(1, tenant_document("beta", id=str(writer.ids[1]), name="Renamed"))
    writer.bump()
    second = registry.get_registry(force=True)
    assert loaded == ["beta"]  # only the one that changed
    by_slug = second.by_slug
    assert by_slug["alpha"] is first.by_slug["alpha"]  # reused, not rebuilt
    assert by_slug["gamma"] is first.by_slug["gamma"]
    assert by_slug["beta"].document.name == "Renamed"
    loaded.clear()

    writer.bump()  # a revision with nothing new in it
    registry.get_registry(force=True)
    assert loaded == []

    writer.write_secrets(2, random.Random(1))  # only gamma's secrets
    writer.bump()
    registry.get_registry(force=True)
    assert loaded == ["gamma"]
    loaded.clear()
    Tenant.objects.using("owner").filter(pk=writer.ids[0]).delete()  # purged
    writer.bump()
    after = registry.get_registry(force=True)
    assert loaded == [] and "alpha" not in after.by_slug


def test_a_quiet_reload_costs_as_many_queries_as_a_read_and_loads_nothing(
    django_assert_num_queries: Any,
) -> None:
    writer = Writer()
    writer.write_document(0, tenant_document("alpha", id=str(writer.ids[0])))
    writer.bump()
    revision = registry.read_config()
    assert revision.fingerprints is not None
    with django_assert_num_queries(7):  # the same 7 as a full read: no payload query more
        quiet = registry.read_config(known=revision.fingerprints)
    assert quiet.sources == []


def test_a_tenant_purged_and_created_again_with_the_same_id_is_reloaded() -> None:
    """Version numbers restart at 1: the fingerprint carries the row id, which does not."""
    writer = Writer()
    writer.write_document(0, tenant_document("alpha", id=str(writer.ids[0]), name="Old"))
    writer.bump()
    registry.get_registry(force=True)
    Tenant.objects.using("owner").filter(pk=writer.ids[0]).delete()
    writer.write_document(0, tenant_document("alpha", id=str(writer.ids[0]), name="New"))
    writer.bump()
    assert registry.get_registry(force=True).by_slug["alpha"].document.name == "New"


def test_a_failing_incremental_reload_falls_back_to_a_full_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    writer = Writer()
    writer.write_document(0, tenant_document("alpha", id=str(writer.ids[0])))
    writer.bump()
    registry.get_registry(force=True)
    writer.write_document(0, tenant_document("alpha", id=str(writer.ids[0]), name="Second"))
    writer.bump()
    original = registry._read_entries
    calls: list[bool] = []

    def flaky(previous: Any, packs: Any) -> Any:
        calls.append(previous is not None)
        if previous is not None:
            raise ValueError("bug in the incremental path")
        return original(previous, packs)

    monkeypatch.setattr(registry, "_read_entries", flaky)
    assert registry.get_registry(force=True).by_slug["alpha"].document.name == "Second"
    assert calls == [True, False]
