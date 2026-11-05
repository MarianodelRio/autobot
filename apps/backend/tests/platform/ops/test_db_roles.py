"""Database roles: web and worker use fp_app, which cannot
bypass RLS or change the schema; migrations run as fp_owner; the panel's read-only SQL
console uses fp_readonly, which can only SELECT and not read SENSITIVE_TABLES."""

import pytest
from django.core.management import call_command, get_commands, load_command_class
from django.db import DatabaseError, connections, transaction

from autobot.db import grants as db_grants

pytestmark = pytest.mark.django_db(databases=["default", "owner"])


def query(alias: str, sql: str) -> tuple[object, ...]:
    with connections[alias].cursor() as cursor:
        cursor.execute(sql)
        row = cursor.fetchone()
    assert row is not None
    return tuple(row)


def test_aliases_use_their_roles() -> None:
    assert query("default", "SELECT current_user") == ("fp_app",)
    assert query("owner", "SELECT current_user") == ("fp_owner",)


def test_fp_app_cannot_bypass_rls_nor_administer() -> None:
    assert query(
        "default",
        "SELECT rolbypassrls, rolsuper, rolcreatedb, rolcreaterole FROM pg_roles"
        " WHERE rolname = 'fp_app'",
    ) == (False, False, False, False)


def test_fp_owner_bypasses_rls_but_is_not_superuser() -> None:
    assert query(
        "owner", "SELECT rolbypassrls, rolsuper FROM pg_roles WHERE rolname = 'fp_owner'"
    ) == (True, False)


@pytest.mark.parametrize(
    "ddl",
    [
        "CREATE TABLE fp_app_probe (id int)",
        "CREATE TEMP TABLE fp_app_probe (id int)",
        "CREATE SCHEMA fp_app_probe",
        "CREATE FUNCTION fp_app_probe() RETURNS int LANGUAGE sql AS 'SELECT 1'",
        "ALTER TABLE django_migrations ADD COLUMN probe int",
        "DROP TABLE django_migrations",
        "TRUNCATE django_migrations",
        "ALTER TABLE django_migrations DISABLE ROW LEVEL SECURITY",
    ],
)
def test_fp_app_cannot_change_the_schema(ddl: str) -> None:
    with (
        pytest.raises(DatabaseError, match="permission denied|must be owner"),
        transaction.atomic(using="default"),
        connections["default"].cursor() as cursor,
    ):
        cursor.execute(ddl)


def test_migrations_ran_as_fp_owner_and_fp_app_can_use_the_tables() -> None:
    owners = query(
        "owner",
        "SELECT array_agg(DISTINCT tableowner) FROM pg_tables WHERE schemaname = 'public'",
    )
    assert owners == (["fp_owner"],)
    assert query(
        "default",
        "SELECT has_table_privilege('django_migrations', 'SELECT, INSERT, UPDATE, DELETE')",
    ) == (True,)


def test_migrate_uses_the_owner_alias_by_default() -> None:
    assert get_commands()["migrate"] == "autobot"  # what `manage.py migrate` runs
    command = load_command_class("autobot", "migrate")
    options = command.create_parser("manage.py", "migrate").parse_args([])
    assert options.database == "owner"


def test_fp_readonly_exists_without_bypassrls() -> None:
    assert query(
        "owner",
        "SELECT rolbypassrls, rolsuper, rolcreatedb, rolcreaterole FROM pg_roles"
        " WHERE rolname = 'fp_readonly'",
    ) == (False, False, False, False)


def test_fp_readonly_cannot_read_sensitive_tables() -> None:
    for table in db_grants.SENSITIVE_TABLES:
        assert query(
            "owner", f"SELECT has_table_privilege('fp_readonly', '{table}', 'SELECT')"
        ) == (False,)


def test_fp_readonly_can_read_ordinary_tables() -> None:
    assert query("owner", "SELECT has_table_privilege('fp_readonly', 'tenant', 'SELECT')") == (
        True,
    )
    assert query("owner", "SELECT has_table_privilege('fp_readonly', 'tenant', 'INSERT')") == (
        False,
    )


def test_fp_app_cannot_write_tenant() -> None:
    for privilege in ("INSERT", "UPDATE", "DELETE"):
        assert query("owner", f"SELECT has_table_privilege('fp_app', 'tenant', '{privilege}')") == (
            False,
        )


def test_apply_grants_is_idempotent() -> None:
    db_grants.apply(connections["owner"])
    db_grants.apply(connections["owner"])


def test_apply_grants_reapplies_a_revoked_grant() -> None:
    with connections["owner"].cursor() as cursor:
        cursor.execute("REVOKE SELECT ON tenant FROM fp_readonly")
    assert query("owner", "SELECT has_table_privilege('fp_readonly', 'tenant', 'SELECT')") == (
        False,
    )
    call_command("apply_grants")
    assert query("owner", "SELECT has_table_privilege('fp_readonly', 'tenant', 'SELECT')") == (
        True,
    )


@pytest.mark.parametrize(
    "table",
    ["tenant_document_version", "tenant_dataset_version", "tenant_secret", "config_revision"],
)
def test_fp_app_reads_config_tables_but_cannot_write_them(table: str) -> None:
    assert query("owner", f"SELECT has_table_privilege('fp_app', '{table}', 'SELECT')") == (True,)
    for privilege in ("INSERT", "UPDATE", "DELETE"):
        assert query(
            "owner", f"SELECT has_table_privilege('fp_app', '{table}', '{privilege}')"
        ) == (False,)


@pytest.mark.parametrize(
    "table",
    ["tenant_document_version", "tenant_dataset_version", "tenant_secret", "config_revision"],
)
def test_fp_owner_writes_config_tables(table: str) -> None:
    for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE"):
        assert query(
            "owner", f"SELECT has_table_privilege('fp_owner', '{table}', '{privilege}')"
        ) == (True,)


def test_fp_readonly_cannot_read_tenant_secret() -> None:
    assert query(
        "owner", "SELECT has_table_privilege('fp_readonly', 'tenant_secret', 'SELECT')"
    ) == (False,)
