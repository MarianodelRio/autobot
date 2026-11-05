"""Adds `audit_event` (ADR-009): no RLS, since the panel and operator commands write and
read it across tenants. `fp_app` never reads or writes it (autobot/db/grants.py)."""

import uuid

from django.db import migrations, models
from django.utils import timezone

from autobot.db import grants as db_grants


def apply_grants(apps: object, schema_editor: object) -> None:
    db_grants.apply(schema_editor.connection)  # type: ignore[attr-defined]


class Migration(migrations.Migration):
    dependencies = [
        ("autobot", "0011_apply_grants"),
    ]

    operations = [
        migrations.CreateModel(
            name="AuditEvent",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid7, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("at", models.DateTimeField(db_index=True, default=timezone.now)),
                ("actor", models.CharField(max_length=150)),
                ("action", models.CharField(db_index=True, max_length=64)),
                ("tenant_id", models.UUIDField(blank=True, db_index=True, null=True)),
                ("target_type", models.CharField(blank=True, default="", max_length=64)),
                ("target_id", models.CharField(blank=True, default="", max_length=200)),
                ("summary", models.TextField()),
                ("details", models.JSONField(default=dict)),
            ],
            options={"db_table": "audit_event"},
        ),
        migrations.RunPython(apply_grants, migrations.RunPython.noop),
    ]
