from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("autobot", "0032_panel_feed_indexes"),
    ]

    operations = [
        migrations.AddField(
            model_name="outboundmessage",
            name="not_after",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
