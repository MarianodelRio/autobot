# Adds a `readonly_all` policy next to every `tenant_isolation`
# one, so the SQL console's "every client" mode has no RLS filtering to fight.

from typing import Any

from django.db import migrations

READONLY_ALL_SQL = (
    "CREATE POLICY readonly_all ON {table} FOR SELECT TO fp_readonly"
    " USING (current_setting('app.readonly_all', true) = 'on')"
)


def create_readonly_all(apps: Any, schema_editor: Any) -> None:
    connection = schema_editor.connection
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1 FROM pg_roles WHERE rolname = 'fp_readonly'")
        if cursor.fetchone() is None:
            raise RuntimeError("fp_readonly role does not exist: run init-roles.sh first")
        cursor.execute(
            "SELECT tablename FROM pg_policies"
            " WHERE schemaname = 'public' AND policyname = 'tenant_isolation'"
        )
        tables = [name for (name,) in cursor.fetchall()]
    with connection.cursor() as cursor:
        for table in tables:
            cursor.execute(READONLY_ALL_SQL.format(table=table))


def drop_readonly_all(apps: Any, schema_editor: Any) -> None:
    connection = schema_editor.connection
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT tablename FROM pg_policies"
            " WHERE schemaname = 'public' AND policyname = 'readonly_all'"
        )
        tables = [name for (name,) in cursor.fetchall()]
    with connection.cursor() as cursor:
        for table in tables:
            cursor.execute(f"DROP POLICY readonly_all ON {table}")


class Migration(migrations.Migration):
    dependencies = [
        ("autobot", "0018_savedquery"),
    ]

    operations = [
        migrations.RunPython(create_readonly_all, drop_readonly_all),
    ]
