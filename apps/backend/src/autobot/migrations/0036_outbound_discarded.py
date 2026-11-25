"""`outbound_message.status` gains `discarded` (ADR-031): a person decided not to send it."""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("autobot", "0035_config_follower"),
    ]

    operations = [
        migrations.AlterField(
            model_name="outboundmessage",
            name="status",
            field=models.CharField(
                choices=[
                    ("pending", "Pending"),
                    ("sending", "Sending"),
                    ("sent", "Sent"),
                    ("failed", "Failed"),
                    ("unknown", "Unknown"),
                    ("expired", "Expired"),
                    ("discarded", "Discarded"),
                ],
                db_default="pending",
                default="pending",
                max_length=10,
            ),
        ),
    ]
