"""`ops_alert` becomes the incident (ADR-031): review watermark, case count and time, and
kind-specific details. Expand only: new columns with database defaults; no RLS (by design,
ADR-009) and no change of grants."""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("autobot", "0036_outbound_discarded"),
    ]

    operations = [
        migrations.AddField(
            model_name="opsalert",
            name="review_watermark",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="opsalert",
            name="case_count",
            field=models.PositiveIntegerField(db_default=0, default=0),
        ),
        migrations.AddField(
            model_name="opsalert",
            name="last_case_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="opsalert",
            name="details",
            field=models.JSONField(db_default={}, default=dict),
        ),
    ]
