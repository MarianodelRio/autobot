"""Adds `metric_event`, the table `RecordMetric` writes to for the owner's periodic
summary, with the same RLS policy as every other `TenantScoped` table (migration 0002).
A new table and policy, nothing existing changes, so no special approval is needed."""

import uuid

import django.db.models.deletion
from django.db import migrations, models

TABLE = "metric_event"
TENANT = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"


def rls() -> migrations.RunSQL:
    check = f"tenant_id = {TENANT}"
    return migrations.RunSQL(
        sql=[
            f"ALTER TABLE {TABLE} ENABLE ROW LEVEL SECURITY",
            f"ALTER TABLE {TABLE} FORCE ROW LEVEL SECURITY",
            f"CREATE POLICY tenant_isolation ON {TABLE} USING ({check}) WITH CHECK ({check})",
        ],
        reverse_sql=[
            f"DROP POLICY tenant_isolation ON {TABLE}",
            f"ALTER TABLE {TABLE} NO FORCE ROW LEVEL SECURITY",
            f"ALTER TABLE {TABLE} DISABLE ROW LEVEL SECURITY",
        ],
    )


class Migration(migrations.Migration):
    dependencies = [
        ("flowpilot", "0008_demo_channels"),
    ]

    operations = [
        migrations.CreateModel(
            name="MetricEvent",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid7,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("kind", models.CharField(max_length=64)),
                ("value", models.DecimalField(decimal_places=2, max_digits=12)),
                ("idem_key", models.TextField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "tenant",
                    models.ForeignKey(
                        db_index=False,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="+",
                        to="flowpilot.tenant",
                    ),
                ),
            ],
            options={
                "db_table": "metric_event",
                "indexes": [
                    models.Index(
                        fields=["tenant", "kind", "created_at"],
                        name="metric_event_kind_idx",
                    )
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("tenant", "idem_key"), name="metric_event_idem_key_uniq"
                    )
                ],
            },
        ),
        rls(),
    ]
