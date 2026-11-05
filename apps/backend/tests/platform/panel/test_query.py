"""Read-only SQL console: the `readonly_all` policy itself, and the
guards and behaviour of `panel.services.query.run`."""

from typing import Any

import pytest
from django.db import connections, transaction

from autobot.ops.models import AuditEvent
from autobot.panel.errors import ApiError
from autobot.panel.services import query
from autobot.runtime.models import Contact
from autobot.tenancy.models import Tenant
from autobot.tenancy.tx import tenant_tx
from tests.helpers.integration import tg_tenant
from tests.platform.panel.conftest import post

pytestmark = pytest.mark.django_db(transaction=True, databases=["default", "owner", "readonly"])


def _seed_two_tenants(tenants: Any) -> tuple[Tenant, Tenant]:
    doc_a, doc_b = tg_tenant("querya"), tg_tenant("queryb")
    tenants(doc_a, doc_b)
    tenant_a = Tenant.objects.using("owner").get(pk=doc_a["id"])
    tenant_b = Tenant.objects.using("owner").get(pk=doc_b["id"])
    with tenant_tx(tenant_a.id):
        Contact.objects.create(tenant_id=tenant_a.id, channel="main", external_id="a1")
    with tenant_tx(tenant_b.id):
        Contact.objects.create(tenant_id=tenant_b.id, channel="main", external_id="b1")
    return tenant_a, tenant_b


def test_readonly_all_policy_needs_the_setting(tenants: Any) -> None:
    tenant_a, _ = _seed_two_tenants(tenants)
    with transaction.atomic(using="readonly"):
        with connections["readonly"].cursor() as cursor:
            cursor.execute("SELECT count(*) FROM contact")
            assert cursor.fetchone() == (0,)
            cursor.execute("SELECT set_config('app.readonly_all', 'on', true)")
            cursor.execute("SELECT count(*) FROM contact")
            assert cursor.fetchone() == (2,)
        transaction.set_rollback(True, using="readonly")
    with transaction.atomic(using="readonly"):
        with connections["readonly"].cursor() as cursor:
            cursor.execute("SELECT set_config('app.tenant_id', %s, true)", [str(tenant_a.id)])
            cursor.execute("SELECT count(*) FROM contact")
            assert cursor.fetchone() == (1,)
        transaction.set_rollback(True, using="readonly")


def test_run_without_tenant_sees_every_client(tenants: Any) -> None:
    _seed_two_tenants(tenants)
    result = query.run("SELECT count(*) FROM contact", tenant_id=None, actor="operator")
    assert result.rows == [[2]]


def test_run_with_tenant_sees_only_its_rows(tenants: Any) -> None:
    tenant_a, _ = _seed_two_tenants(tenants)
    result = query.run("SELECT count(*) FROM contact", tenant_id=tenant_a.id, actor="operator")
    assert result.rows == [[1]]


def test_like_wildcard_is_not_interpreted_as_a_parameter(tenants: Any) -> None:
    _seed_two_tenants(tenants)
    result = query.run(
        "SELECT count(*) FROM contact WHERE external_id LIKE '%1'",
        tenant_id=None,
        actor="operator",
    )
    assert result.rows == [[2]]


def test_columns_report_their_pg_type() -> None:
    result = query.run("SELECT 1 AS n", tenant_id=None, actor="operator")
    assert result.columns[0].name == "n"
    assert result.columns[0].type == "int4"
    assert result.rows == [[1]]


@pytest.mark.parametrize(
    "sql",
    [
        "INSERT INTO contact (id) VALUES ('00000000-0000-0000-0000-000000000000')",
        "UPDATE contact SET channel = 'x'",
        "DELETE FROM contact",
        "CREATE TABLE query_test_reject (id integer)",
        "SELECT 1; SELECT 2",
        "EXPLAIN SELECT 1",
        "",
        "x" * 20_001,
    ],
)
def test_rejects_anything_but_one_select(sql: str) -> None:
    with pytest.raises(ApiError) as excinfo:
        query.run(sql, tenant_id=None, actor="operator")
    assert excinfo.value.status == 400


def test_sensitive_table_is_permission_denied() -> None:
    with pytest.raises(ApiError) as excinfo:
        query.run("SELECT * FROM tenant_secret", tenant_id=None, actor="operator")
    assert excinfo.value.status == 400
    assert "permission denied" in excinfo.value.message


def test_statement_timeout_cuts_a_slow_query() -> None:
    with pytest.raises(ApiError):
        query.run("SELECT pg_sleep(11)", tenant_id=None, actor="operator")


def test_truncated_to_1000_rows() -> None:
    result = query.run(
        "SELECT i FROM generate_series(1, 1500) AS i", tenant_id=None, actor="operator"
    )
    assert result.truncated
    assert len(result.rows) == 1000


def test_audits_the_query() -> None:
    query.run("SELECT 1", tenant_id=None, actor="operator")
    event = AuditEvent.objects.using("owner").filter(action="data.query").latest("at")
    assert event.actor == "operator"
    assert event.details["sql"] == "SELECT 1"


def test_no_setting_or_transaction_remains_after_the_query() -> None:
    query.run("SELECT 1", tenant_id=None, actor="operator")
    assert not connections["readonly"].in_atomic_block
    with connections["readonly"].cursor() as cursor:
        cursor.execute("SELECT current_setting('app.readonly_all', true)")
        assert cursor.fetchone()[0] in (None, "")


def test_query_endpoint(authed_client: Any, tenants: Any) -> None:
    tenant_a, _ = _seed_two_tenants(tenants)
    scoped = post(
        authed_client,
        "data/query",
        {"sql": "SELECT count(*) FROM contact", "tenant": tenant_a.slug},
    )
    assert scoped.status_code == 200, scoped.content
    assert scoped.json()["rows"] == [[1]]

    every_client = post(authed_client, "data/query", {"sql": "SELECT count(*) FROM contact"})
    assert every_client.json()["rows"] == [[2]]

    assert (
        post(authed_client, "data/query", {"sql": "SELECT 1", "tenant": "nope"}).status_code == 404
    )
    assert post(authed_client, "data/query", {"sql": "DROP TABLE contact"}).status_code == 400
