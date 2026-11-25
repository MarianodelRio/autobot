"""`config_follower`: the configuration revision each live process has loaded (ADR-030)."""

from typing import Any

from django.db import migrations, models

from autobot.db import grants as db_grants


def apply_grants(apps: Any, schema_editor: Any) -> None:
    db_grants.apply(schema_editor.connection)


class Migration(migrations.Migration):
    dependencies = [
        ("autobot", "0034_contact_drop_opt_out"),
    ]

    operations = [
        migrations.CreateModel(
            name="ConfigFollower",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("service", models.CharField(max_length=64)),
                ("host", models.CharField(max_length=128)),
                ("pid", models.IntegerField()),
                ("revision", models.BigIntegerField()),
                ("started_at", models.DateTimeField()),
                ("seen_at", models.DateTimeField(db_index=True)),
            ],
            options={"db_table": "config_follower"},
        ),
        migrations.AddConstraint(
            model_name="configfollower",
            constraint=models.UniqueConstraint(
                fields=("host", "pid"), name="config_follower_host_pid"
            ),
        ),
        migrations.RunPython(apply_grants, migrations.RunPython.noop),
    ]
