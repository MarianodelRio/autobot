"""Reapplies the desired PostgreSQL permissions (autobot/db/grants.py, ADR-009) whenever this
migration runs: on a fresh database, and on every future migration that touches tables
or permissions. Depends on auth's and sessions' own migrations so fp_readonly's
SELECT grant and the SENSITIVE_TABLES revokes see those tables already created.

Approved by the person on 2026-11-03 (see docs/arquitectura/adr/ADR-009-config-en-bd.md)."""

from django.db import migrations

from autobot.db import grants as db_grants


def apply_grants(apps: object, schema_editor: object) -> None:
    db_grants.apply(schema_editor.connection)  # type: ignore[attr-defined]


class Migration(migrations.Migration):
    dependencies = [
        ("autobot", "0010_owner_link"),
        ("auth", "0012_alter_user_first_name_max_length"),
        ("sessions", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(apply_grants, migrations.RunPython.noop),
    ]
