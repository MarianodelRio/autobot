"""Reapplies db_grants.py (ADR-009): `fp_app` loses all access to Django's own
auth/session/OTP tables now that `AuthDatabaseRouter` routes them to `fp_owner` (T14).

Approved by the person on 2026-11-03 (see docs/adr/ADR-009-config-en-bd.md)."""

from django.db import migrations

from autobot import db_grants


def apply_grants(apps: object, schema_editor: object) -> None:
    db_grants.apply(schema_editor.connection)  # type: ignore[attr-defined]


class Migration(migrations.Migration):
    dependencies = [
        ("autobot", "0016_system_sample"),
    ]

    operations = [
        migrations.RunPython(apply_grants, migrations.RunPython.noop),
    ]
