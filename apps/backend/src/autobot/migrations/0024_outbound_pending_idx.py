"""A partial index for `outbound_message` rows still `pending`, mirroring the existing
one for `unknown` (`0007_retention_indexes`): cheap to keep up to date (few rows match
at any time) and avoids a full scan when something needs to find them."""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("autobot", "0023_notification_contact_fk"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="outboundmessage",
            index=models.Index(
                condition=models.Q(("status", "pending")),
                fields=["tenant", "created_at"],
                name="outbound_pending_idx",
            ),
        ),
    ]
