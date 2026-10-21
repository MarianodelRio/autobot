"""Generic tenant isolation test (design.md §12.2, T-2.3), mandatory in CI.

For every model with `tenant_id`, with tenants A and B and as fp_app: A does not read,
update, delete or insert B's rows, cannot point to them, and without a tenant nothing is
read or written. Every such model needs a factory below and an RLS policy, and every table
with a `tenant_id` column needs its policy, so a new table without one fails here.
Transactional tests: the rows really commit, as in production.
"""

import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import pytest
from django.apps import apps
from django.db import DatabaseError, IntegrityError, connections, models, transaction

from flowpilot.models import (
    Contact,
    Conversation,
    InboundEvent,
    Notification,
    OutboundMessage,
    Tenant,
    TestSession,
)
from flowpilot.tenancy.tx import tenant_tx

pytestmark = pytest.mark.django_db(transaction=True, databases=["default", "owner"])
NOW = datetime(2026, 10, 5, 10, tzinfo=UTC)

# Platform tables with tenant_id but no RLS by design (§6.5: written before the tenant is
# known, only used by the test bot selector).
PLATFORM_MODELS: set[type[models.Model]] = {TestSession}
PLATFORM_TABLES = {m._meta.db_table for m in PLATFORM_MODELS}
RLS_ERROR = "row-level security"


# ── Factories: called inside tenant_tx(t), each creates a row of tenant t. Parents are
# created only when not given, so a test can pass existing ones. ───────────────────


def _contact(t: Tenant, **o: Any) -> Contact:
    return Contact.objects.create(
        **{"tenant_id": t.id, "channel": "main", "external_id": uuid.uuid4().hex, **o}
    )


def _event(t: Tenant, **o: Any) -> InboundEvent:
    return InboundEvent.objects.create(
        **{
            "tenant_id": t.id,
            "channel": "main",
            "kind": "message",
            "provider_event_id": uuid.uuid4().hex,
            "payload": {},
            "status": "pending",
            "received_at": NOW,
            **o,
        }
    )


def _conversation(t: Tenant, **o: Any) -> Conversation:
    if "contact" not in o:
        o["contact"] = _contact(t)
    return Conversation.objects.create(tenant_id=t.id, **o)


def _outbound(t: Tenant, **o: Any) -> OutboundMessage:
    if "contact" not in o:
        o["contact"] = _contact(t)
    if "inbound_event" not in o:
        o["inbound_event"] = _event(t)
    return OutboundMessage.objects.create(
        **{
            "tenant_id": t.id,
            "channel": "main",
            "idem_key": uuid.uuid4().hex,
            "kind": "reply",
            "payload": {},
            **o,
        }
    )


def _notification(t: Tenant, **o: Any) -> Notification:
    return Notification.objects.create(
        **{"tenant_id": t.id, "idem_key": uuid.uuid4().hex, "kind": "k", "text": "t", **o}
    )


FACTORIES: dict[type[models.Model], Callable[..., models.Model]] = {
    Contact: _contact,
    Conversation: _conversation,
    InboundEvent: _event,
    OutboundMessage: _outbound,
    Notification: _notification,
}
MODELS = sorted(FACTORIES, key=str)


def tenant_models() -> set[type[models.Model]]:
    return {
        m
        for m in apps.get_app_config("flowpilot").get_models()
        if any(f.name == "tenant" for f in m._meta.get_fields())
    }


def parent_fields(model: type[models.Model]) -> dict[str, type[models.Model]]:
    """Field name → parent model, for every reference to another tenant-scoped row."""
    return {
        field.name: field.related_model
        for field in model._meta.get_fields()
        if isinstance(field, models.ForeignKey)
        and isinstance(field.related_model, type)
        and field.related_model in FACTORIES
    }


def tenant_foreign_keys() -> list[tuple[type[models.Model], str, type[models.Model]]]:
    return [(m, name, parent) for m in MODELS for name, parent in parent_fields(m).items()]


def parents_of(model: type[models.Model], t: Tenant) -> dict[str, models.Model]:
    """Parent rows of tenant t for a row of `model` (creates them in tenant_tx(t))."""
    with tenant_tx(t.id):
        return {name: FACTORIES[parent](t) for name, parent in parent_fields(model).items()}


def isolation_problems(table: str, column: str = "tenant_id") -> list[str]:
    """What is missing for `table` to be isolated: RLS enabled and forced, and
    tenant_isolation as its only policy, for every command, on reads and on writes."""
    with connections["owner"].cursor() as cursor:
        cursor.execute(
            "SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE relname = %s",
            [table],
        )
        enabled, forced = cursor.fetchone() or (False, False)
        cursor.execute(
            "SELECT policyname, cmd, permissive, qual, with_check FROM pg_policies"
            " WHERE tablename = %s",
            [table],
        )
        policies = cursor.fetchall()
    setting = "NULLIF(current_setting('app.tenant_id'::text, true), ''::text)"
    expected = f"({column} = ({setting})::uuid)"
    problems = []
    if not enabled:
        problems.append("RLS not enabled")
    if not forced:
        problems.append("RLS not forced")
    if not policies:
        problems.append("no tenant_isolation policy")
    elif policies != [("tenant_isolation", "ALL", "PERMISSIVE", expected, expected)]:
        problems.append(f"unexpected policies {policies}")
    return problems


def owner_count(model: type[models.Model], **filters: Any) -> int:
    return int(model._default_manager.using("owner").filter(**filters).count())


def execute(sql: str, params: list[Any]) -> int:
    with connections["default"].cursor() as cursor:
        cursor.execute(sql, params)
        return int(cursor.rowcount)


def current_tenant_setting() -> str | None:
    with connections["default"].cursor() as cursor:
        cursor.execute("SELECT current_setting('app.tenant_id', true)")
        row = cursor.fetchone()
    return None if row is None else row[0]


def make_tenant(slug: str) -> Tenant:
    return Tenant.objects.using("owner").create(
        id=uuid.uuid7(),
        slug=slug,
        name=slug,
        pack="toy",
        status="active",
        timezone="Europe/Madrid",
        synced_at=NOW,
    )


@pytest.fixture
def tenants() -> tuple[Tenant, Tenant]:
    return make_tenant("a"), make_tenant("b")


def rows(model: type[models.Model], a: Tenant, b: Tenant) -> tuple[models.Model, models.Model]:
    with tenant_tx(a.id):
        row_a = FACTORIES[model](a)
    with tenant_tx(b.id):
        row_b = FACTORIES[model](b)
    return row_a, row_b


# ── Coverage: every tenant table is isolated and tested ──────────────────


def test_every_tenant_model_has_a_factory_or_is_a_platform_table() -> None:
    assert tenant_models() == set(FACTORIES) | PLATFORM_MODELS


@pytest.mark.parametrize("model", sorted(tenant_models() - PLATFORM_MODELS, key=str))
def test_every_tenant_model_has_its_policy(model: type[models.Model]) -> None:
    assert isolation_problems(model._meta.db_table) == []


def test_every_table_with_tenant_id_has_its_policy() -> None:
    """Also tables that no model of the app declares (another app, raw SQL)."""
    with connections["owner"].cursor() as cursor:
        cursor.execute(
            "SELECT table_name FROM information_schema.columns"
            " WHERE table_schema = 'public' AND column_name = 'tenant_id'"
        )
        tables = {name for (name,) in cursor.fetchall()} - PLATFORM_TABLES
    assert tables  # the query found the tenant tables
    assert {t: isolation_problems(t) for t in tables if isolation_problems(t)} == {}


def test_tenant_table_has_its_policy_on_id() -> None:
    assert isolation_problems("tenant", column="id") == []


def test_a_table_without_policy_is_detected() -> None:
    with connections["owner"].cursor() as cursor:
        cursor.execute("CREATE TABLE isolation_probe (id uuid PRIMARY KEY, tenant_id uuid)")
    try:
        assert isolation_problems("isolation_probe") == [
            "RLS not enabled",
            "RLS not forced",
            "no tenant_isolation policy",
        ]
    finally:
        with connections["owner"].cursor() as cursor:
            cursor.execute("DROP TABLE isolation_probe")


def test_an_extra_permissive_policy_is_detected() -> None:
    with connections["owner"].cursor() as cursor:
        cursor.execute("CREATE POLICY leak ON notification FOR INSERT WITH CHECK (true)")
    try:
        assert isolation_problems("notification")[0].startswith("unexpected policies")
    finally:
        with connections["owner"].cursor() as cursor:
            cursor.execute("DROP POLICY leak ON notification")


# ── Isolation, for every tenant model ────────────────────────────────────


@pytest.mark.parametrize("model", MODELS)
def test_tenant_reads_only_its_rows(
    model: type[models.Model], tenants: tuple[Tenant, Tenant]
) -> None:
    a, b = tenants
    row_a, row_b = rows(model, a, b)
    with tenant_tx(a.id):
        manager = model._default_manager
        assert manager.filter(pk=row_a.pk).exists()
        assert not manager.filter(pk=row_b.pk).exists()
        assert set(manager.values_list("tenant_id", flat=True)) == {a.id}


@pytest.mark.parametrize("model", MODELS)
def test_tenant_cannot_update_or_delete_other_rows(
    model: type[models.Model], tenants: tuple[Tenant, Tenant]
) -> None:
    a, b = tenants
    _, row_b = rows(model, a, b)
    table = model._meta.db_table
    with tenant_tx(a.id):
        assert execute(f"UPDATE {table} SET tenant_id = tenant_id WHERE id = %s", [row_b.pk]) == 0
        assert execute(f"DELETE FROM {table} WHERE id = %s", [row_b.pk]) == 0
        assert model._default_manager.filter(pk=row_b.pk).update(tenant_id=a.id) == 0
    assert owner_count(model, pk=row_b.pk, tenant_id=b.id) == 1


@pytest.mark.parametrize("model", MODELS)
def test_tenant_cannot_insert_rows_of_another_tenant(
    model: type[models.Model], tenants: tuple[Tenant, Tenant]
) -> None:
    a, b = tenants
    # B's parents exist, so only RLS can stop A from inserting the row itself.
    parents_b = parents_of(model, b)
    with pytest.raises(DatabaseError, match=RLS_ERROR), tenant_tx(a.id):
        FACTORIES[model](b, **parents_b)
    assert owner_count(model, tenant_id=b.id) == 0


@pytest.mark.parametrize("model", MODELS)
def test_tenant_cannot_move_its_rows_to_another_tenant(
    model: type[models.Model], tenants: tuple[Tenant, Tenant]
) -> None:
    a, b = tenants
    row_a, _ = rows(model, a, b)
    table = model._meta.db_table
    with pytest.raises(DatabaseError, match=RLS_ERROR), tenant_tx(a.id):
        execute(f"UPDATE {table} SET tenant_id = %s WHERE id = %s", [b.id, row_a.pk])
    assert owner_count(model, pk=row_a.pk, tenant_id=a.id) == 1


@pytest.mark.parametrize(
    ("model", "field", "parent"),
    tenant_foreign_keys(),
    ids=lambda v: v if isinstance(v, str) else getattr(v, "__name__", str(v)),
)
def test_tenant_cannot_point_to_rows_of_another_tenant(
    model: type[models.Model],
    field: str,
    parent: type[models.Model],
    tenants: tuple[Tenant, Tenant],
) -> None:
    a, b = tenants
    with tenant_tx(b.id):
        parent_b = FACTORIES[parent](b)
    composite_fk = r'violates foreign key constraint "\w+_fk"'
    with pytest.raises(IntegrityError, match=composite_fk), tenant_tx(a.id):
        FACTORIES[model](a, **{field: parent_b})


@pytest.mark.parametrize("model", MODELS)
def test_without_tenant_nothing_is_read_or_written(
    model: type[models.Model], tenants: tuple[Tenant, Tenant]
) -> None:
    a, b = tenants
    row_a, _ = rows(model, a, b)  # leaves the persistent connection after two tenant_tx
    parents_a = parents_of(model, a)
    table = model._meta.db_table
    assert model._default_manager.count() == 0
    assert execute(f"UPDATE {table} SET tenant_id = tenant_id WHERE id = %s", [row_a.pk]) == 0
    assert execute(f"DELETE FROM {table} WHERE id = %s", [row_a.pk]) == 0
    with pytest.raises(DatabaseError, match=RLS_ERROR), transaction.atomic(using="default"):
        FACTORIES[model](a, **parents_a)
    assert owner_count(model, pk=row_a.pk) == 1


def test_tenant_sees_only_its_own_tenant_row(tenants: tuple[Tenant, Tenant]) -> None:
    a, _ = tenants
    with tenant_tx(a.id):
        assert list(Tenant.objects.values_list("id", flat=True)) == [a.id]
    assert Tenant.objects.count() == 0


def test_platform_tables_need_no_tenant(tenants: tuple[Tenant, Tenant]) -> None:
    a, _ = tenants
    TestSession.objects.create(telegram_user_id=1, tenant_id=a.id, selected_at=NOW)
    assert TestSession.objects.count() == 1


# ── tenant_tx ─────────────────────────────────────────────────────────────


def test_tenant_tx_cannot_be_nested(tenants: tuple[Tenant, Tenant]) -> None:
    a, b = tenants
    with pytest.raises(RuntimeError, match="durable"), tenant_tx(a.id), tenant_tx(b.id):
        pass


def test_tenant_tx_cannot_run_inside_another_transaction(tenants: tuple[Tenant, Tenant]) -> None:
    a, _ = tenants
    with (
        pytest.raises(RuntimeError, match="durable"),
        transaction.atomic(using="default"),
        tenant_tx(a.id),
    ):
        pass


# Inside a test transaction tenant_tx is a savepoint: the setting would outlive the block
# if tenant_tx did not clear it. These tests check exactly that case (not transactional).


@pytest.mark.django_db(databases=["default"])
def test_no_tenant_remains_after_the_block() -> None:
    with tenant_tx(uuid.uuid7()):
        assert current_tenant_setting() != ""
    assert current_tenant_setting() == ""


@pytest.mark.django_db(databases=["default"])
def test_no_tenant_remains_after_an_error() -> None:
    with pytest.raises(ZeroDivisionError), tenant_tx(uuid.uuid7()):
        1 / 0  # noqa: B018
    assert current_tenant_setting() in ("", None)


@pytest.mark.django_db(databases=["default"])
def test_a_block_marked_for_rollback_exits_cleanly() -> None:
    with tenant_tx(uuid.uuid7()):
        transaction.set_rollback(True, using="default")
    assert current_tenant_setting() in ("", None)
