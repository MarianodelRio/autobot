"""Persisted operation alerts: `ops_alert`, no RLS by design (ADR-009),
and `purge_platform_history(cutoff)`, a SECURITY DEFINER function that lets `fp_app`
(no DELETE on `ops_alert` or `audit_event`) erase old platform history without
`BYPASSRLS`.

Approved by the person on 2026-11-03 (see docs/adr/ADR-009-config-en-bd.md)."""

import uuid

from django.db import migrations, models
from django.utils import timezone

from autobot.db import grants as db_grants

PURGE_FUNCTION = """
CREATE FUNCTION purge_platform_history(cutoff timestamptz) RETURNS void
LANGUAGE sql SECURITY DEFINER SET search_path = public, pg_temp AS $$
    DELETE FROM ops_alert WHERE resolved_at < cutoff;
    DELETE FROM audit_event WHERE at < cutoff;
$$
"""


def apply_grants(apps: object, schema_editor: object) -> None:
    db_grants.apply(schema_editor.connection)  # type: ignore[attr-defined]


class Migration(migrations.Migration):
    dependencies = [
        ("autobot", "0014_outbound_sent_index"),
    ]

    operations = [
        migrations.CreateModel(
            name="OpsAlert",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid7, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("kind", models.CharField(db_index=True, max_length=64)),
                ("tenant_id", models.UUIDField(blank=True, db_index=True, null=True)),
                ("severity", models.CharField(max_length=16)),
                ("text", models.TextField()),
                ("first_seen_at", models.DateTimeField(default=timezone.now)),
                ("last_seen_at", models.DateTimeField(default=timezone.now)),
                ("occurrences", models.PositiveIntegerField(default=1)),
                ("sent_count", models.PositiveIntegerField(default=0)),
                ("last_sent_at", models.DateTimeField(blank=True, null=True)),
                ("last_delivery", models.CharField(blank=True, default="", max_length=16)),
                ("auto_resolves", models.BooleanField(default=True)),
                ("resolved_at", models.DateTimeField(blank=True, null=True)),
                ("resolved_by", models.CharField(blank=True, default="", max_length=150)),
            ],
            options={"db_table": "ops_alert"},
        ),
        migrations.AddConstraint(
            model_name="opsalert",
            constraint=models.UniqueConstraint(
                condition=models.Q(("resolved_at__isnull", True)),
                fields=("kind", "tenant_id"),
                name="ops_alert_one_open",
                nulls_distinct=False,
            ),
        ),
        migrations.RunSQL(
            sql=PURGE_FUNCTION,
            reverse_sql="DROP FUNCTION purge_platform_history(timestamptz)",
        ),
        migrations.RunPython(apply_grants, migrations.RunPython.noop),
    ]
