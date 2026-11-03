"""System samples (DESIGN §7.4), taken every five minutes by ops/check.py: no RLS by
design (ADR-009), since they describe the host, not a tenant. `fp_app` keeps its
default privileges (it also deletes the ones older than 62 days)."""

import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("autobot", "0015_ops_alert"),
    ]

    operations = [
        migrations.CreateModel(
            name="SystemSample",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "taken_at",
                    models.DateTimeField(db_index=True, default=django.utils.timezone.now),
                ),
                ("cpu_pct", models.FloatField(blank=True, null=True)),
                ("mem_used_pct", models.FloatField(blank=True, null=True)),
                ("load1", models.FloatField(blank=True, null=True)),
                ("disk_used_pct", models.FloatField(blank=True, null=True)),
                ("db_bytes", models.BigIntegerField()),
            ],
            options={
                "db_table": "system_sample",
            },
        ),
    ]
