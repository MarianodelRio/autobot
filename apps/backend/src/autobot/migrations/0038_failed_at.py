"""`failed_at` on `outbound_message` and `notification` (ADR-031): an incident's case time
is when the row became a failure, not when it was created (a resend of an old ambiguous
send that then fails is a new case). Expand only: a nullable column on two tables that
already have RLS; the policies and grants cover the table, so neither changes."""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("autobot", "0037_ops_alert_incidents"),
    ]

    operations = [
        migrations.AddField(
            model_name="outboundmessage",
            name="failed_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="notification",
            name="failed_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
