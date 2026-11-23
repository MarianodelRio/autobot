from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("autobot", "0028_contact_notice_sent_at"),
    ]

    operations = [
        migrations.AddField(
            model_name="outboundmessage",
            name="expires_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
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
                ],
                db_default="pending",
                default="pending",
                max_length=8,
            ),
        ),
    ]
