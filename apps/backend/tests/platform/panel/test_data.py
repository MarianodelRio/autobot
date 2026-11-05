"""Catalogue, masking and saved queries against the real PostgreSQL schema."""

import importlib
import json
from types import SimpleNamespace
from typing import Any

import pytest
from django.apps import apps
from django.core.cache import cache
from django.db import connections

from autobot.ops.models import AuditEvent, SavedQuery
from autobot.panel.services import catalog
from autobot.runtime.models import OwnerLink
from autobot.tenancy.models import Tenant
from tests.helpers.integration import tg_tenant
from tests.platform.panel.conftest import HOST, get, post

pytestmark = pytest.mark.django_db(transaction=True, databases=["default", "owner"])


def test_all_real_tables_are_documented() -> None:
    with connections["owner"].cursor() as cursor:
        tables = set(connections["owner"].introspection.table_names(cursor))
    assert set(catalog.CATALOG) == tables


def test_permissions_are_reapplied() -> None:
    from autobot.db_grants import apply

    apply(connections["owner"])
    with connections["owner"].cursor() as cursor:
        for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE"):
            cursor.execute(
                "SELECT has_table_privilege(%s, %s, %s)", ["fp_app", "saved_query", privilege]
            )
            assert cursor.fetchone() == (False,)
        cursor.execute(
            "SELECT has_table_privilege(%s, %s, %s)",
            ["fp_owner", "saved_query", "SELECT,INSERT,UPDATE,DELETE"],
        )
        assert cursor.fetchone() == (True,)


def test_seed_queries_are_executable() -> None:
    migration = importlib.import_module("autobot.migrations.0018_savedquery")
    migration.seed_queries(apps, SimpleNamespace(connection=connections["owner"]))
    rows = list(SavedQuery.objects.using("owner").order_by("-id")[:4])
    assert len(rows) == 4
    with connections["owner"].cursor() as cursor:
        for query in rows:
            cursor.execute("EXPLAIN " + query.sql)
            assert cursor.fetchall()


def test_catalog_and_six_hidden_columns(authed_client: Any, tenants: Any) -> None:
    doc = tg_tenant()
    tenants(doc)
    tenant = Tenant.objects.using("owner").get(pk=doc["id"])
    OwnerLink.objects.using("owner").create(tenant=tenant, invite_hash="hidden-hash")
    cache.set("test-catalog", "hidden-cache", 60)
    response = get(authed_client, "data/tables")
    assert response.status_code == 200, response.content
    tables = {row["name"]: row for row in response.json()}
    assert set(tables) == set(catalog.CATALOG)
    assert tables["contact"]["rls"]
    assert tables["tenant"]["row_count"] >= 1
    assert any(r["source"] == "contact" for r in tables["tenant"]["incoming"])
    assert tables["tenant_secret"]["rows_by_tenant"]
    for table, field in catalog.HIDDEN_COLUMNS:
        result = get(authed_client, f"data/tables/{table}")
        assert result.status_code == 200, result.content
        data = result.json()
        index = next(i for i, column in enumerate(data["columns"]) if column["name"] == field)
        assert data["columns"][index]["hidden"]
        assert data["rows"], table
        assert all(row[index] == "<oculto>" for row in data["rows"])
    assert get(authed_client, "data/tables/does_not_exist").status_code == 404


def test_saved_queries_crud_and_audit(authed_client: Any) -> None:
    created = post(authed_client, "data/saved-queries", {"name": "Mis datos", "sql": "SELECT 1"})
    assert created.status_code == 200, created.content
    id = created.json()["id"]
    assert any(row["id"] == id for row in get(authed_client, "data/saved-queries").json())
    updated = authed_client.put(
        f"/api/panel/data/saved-queries/{id}",
        data=json.dumps({"name": "Nuevo", "sql": "SELECT 2"}),
        content_type="application/json",
        HTTP_HOST=HOST,
    )
    assert updated.status_code == 200
    assert updated.json()["sql"] == "SELECT 2"
    deleted = authed_client.delete(f"/api/panel/data/saved-queries/{id}", HTTP_HOST=HOST)
    assert deleted.status_code == 204
    assert (
        authed_client.delete(f"/api/panel/data/saved-queries/{id}", HTTP_HOST=HOST).status_code
        == 404
    )
    assert not SavedQuery.objects.using("owner").filter(pk=id).exists()
    assert set(
        AuditEvent.objects.using("owner")
        .filter(target_type="saved_query", target_id=str(id))
        .values_list("action", flat=True)
    ) == {"saved_query.create", "saved_query.update", "saved_query.delete"}
    assert (
        post(authed_client, "data/saved-queries", {"name": "", "sql": "SELECT 1"}).status_code
        == 422
    )


def test_unknown_table_and_binary_preview(
    authed_client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    with connections["owner"].cursor() as cursor:
        cursor.execute(
            "CREATE TABLE catalog_test_preview "
            "(id bigint PRIMARY KEY, created_at timestamptz, data bytea)"
        )
        try:
            cursor.execute(
                "INSERT INTO catalog_test_preview VALUES "
                "(1, '2026-01-01Z', %s), (2, '2026-02-01Z', %s)",
                [b"abc", b"12345"],
            )
            cursor.execute(
                "INSERT INTO catalog_test_preview SELECT i, '2025-01-01Z', NULL "
                "FROM generate_series(3, 25) AS i"
            )
            listed = get(authed_client, "data/tables").json()
            assert (
                next(row for row in listed if row["name"] == "catalog_test_preview")["group"]
                == "Sin catalogar"
            )
            assert get(authed_client, "data/tables/catalog_test_preview").status_code == 404
            monkeypatch.setitem(
                catalog.CATALOG,
                "catalog_test_preview",
                catalog.TableDoc("Prueba", "Prueba", "Prueba", "Prueba", False),
            )
            detail = get(authed_client, "data/tables/catalog_test_preview").json()
            assert len(detail["rows"]) == 20
            assert [row[0] for row in detail["rows"][:2]] == [2, 1]
            assert [row[2] for row in detail["rows"][:2]] == ["<5 bytes>", "<3 bytes>"]
        finally:
            cursor.execute("DROP TABLE catalog_test_preview")


def test_uncatalogued_name_with_quote(authed_client: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    with connections["owner"].cursor() as cursor:
        cursor.execute('CREATE TABLE "catalog_""quoted" (id integer)')
        try:
            cursor.execute('INSERT INTO "catalog_""quoted" VALUES (1), (3), (2)')
            response = get(authed_client, "data/tables")
            assert response.status_code == 200
            table = next(row for row in response.json() if row["name"] == 'catalog_"quoted')
            assert table["group"] == "Sin catalogar"
            # The fallback order is the primary key when no date field exists.
            cursor.execute('ALTER TABLE "catalog_""quoted" ADD PRIMARY KEY (id)')
            monkeypatch.setitem(
                catalog.CATALOG,
                'catalog_"quoted',
                catalog.TableDoc("Prueba", "Prueba", "Prueba", "Prueba", False),
            )
            detail = catalog.table_detail('catalog_"quoted')
            assert [row[0] for row in detail["rows"]] == [3, 2, 1]
            assert detail["row_count"] == 3 and not detail["approx"]
            estimated = catalog._stats('catalog_"quoted', {"estimate": 100000, "bytes": 1}, [], {})
            assert estimated["row_count"] == 100000 and estimated["approx"]
        finally:
            cursor.execute('DROP TABLE "catalog_""quoted"')
