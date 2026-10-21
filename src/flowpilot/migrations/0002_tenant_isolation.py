"""Tenant isolation (design.md §12.1, §12.2). Requires explicit human approval (CLAUDE.md).

1. Composite foreign keys: a child row can only point to a parent of its own tenant.
2. Row level security, forced also for the table owner, on every table with `tenant_id`
   (and on `tenant`, over its own `id`). Without `app.tenant_id` set, no row is visible.
3. fp_app can only read `tenant`.
"""

from django.db import migrations

TENANT = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"

# (table, tenant column) — every table with tenant data. The isolation test (T-2.3) checks
# that no model with tenant_id is missing from here.
RLS_TABLES = [
    ("tenant", "id"),
    ("contact", "tenant_id"),
    ("conversation", "tenant_id"),
    ("inbound_event", "tenant_id"),
    ("outbound_message", "tenant_id"),
    ("notification", "tenant_id"),
]

# (table, constraint, column, parent, on delete)
COMPOSITE_FKS = [
    ("conversation", "conversation_contact_fk", "contact_id", "contact", "CASCADE"),
    ("outbound_message", "outbound_message_contact_fk", "contact_id", "contact", "CASCADE"),
    # Events are deleted after 90 days and messages kept 12 months (§12.3): only the event
    # column is cleared, never tenant_id.
    (
        "outbound_message",
        "outbound_message_inbound_event_fk",
        "inbound_event_id",
        "inbound_event",
        "SET NULL (inbound_event_id)",
    ),
]


def rls(table: str, column: str) -> migrations.RunSQL:
    check = f"{column} = {TENANT}"
    return migrations.RunSQL(
        sql=[
            f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY",
            f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY",
            f"CREATE POLICY tenant_isolation ON {table} USING ({check}) WITH CHECK ({check})",
        ],
        reverse_sql=[
            f"DROP POLICY tenant_isolation ON {table}",
            f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY",
            f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY",
        ],
    )


def composite_fk(
    table: str, name: str, column: str, parent: str, on_delete: str
) -> migrations.RunSQL:
    return migrations.RunSQL(
        sql=(
            f"ALTER TABLE {table} ADD CONSTRAINT {name} FOREIGN KEY (tenant_id, {column})"
            f" REFERENCES {parent} (tenant_id, id) ON DELETE {on_delete}"
        ),
        reverse_sql=f"ALTER TABLE {table} DROP CONSTRAINT {name}",
    )


class Migration(migrations.Migration):
    dependencies = [("flowpilot", "0001_initial")]

    operations = [
        *(composite_fk(*fk) for fk in COMPOSITE_FKS),
        *(rls(table, column) for table, column in RLS_TABLES),
        # Only sync_tenants (as fp_owner) writes the tenant mirror; fp_app just reads it.
        migrations.RunSQL(
            sql="REVOKE INSERT, UPDATE, DELETE ON tenant FROM fp_app",
            reverse_sql="GRANT INSERT, UPDATE, DELETE ON tenant TO fp_app",
        ),
    ]
