"""Database roles: web and worker use fp_app, which cannot
bypass RLS or change the schema; migrations run as fp_owner."""

import pytest
from django.core.management import get_commands, load_command_class
from django.db import DatabaseError, connections, transaction

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
    assert get_commands()["migrate"] == "flowpilot"  # what `manage.py migrate` runs
    command = load_command_class("flowpilot", "migrate")
    options = command.create_parser("manage.py", "migrate").parse_args([])
    assert options.database == "owner"
