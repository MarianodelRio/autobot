"""Links a `notification` to the contact it is about (null for the monthly owner
summary, which is about no single contact). `runtime.privacy.forget` relies on this
FK's CASCADE to erase the client's name from `text` along with everything else."""

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("autobot", "0021_purge_platform_history_min_cutoff"),
    ]

    operations = [
        migrations.AddField(
            model_name="notification",
            name="contact",
            field=models.ForeignKey(
                blank=True,
                db_constraint=False,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="+",
                to="autobot.contact",
            ),
        ),
    ]
