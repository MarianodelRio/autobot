"""Dataset library (ADR-013): `dataset_library_version` is a tenant-independent
version history uploaded by terminal; `TenantDatasetVersion` gains plain (no FK)
columns recording which library entry a client's own copy came from."""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("autobot", "0025_demo_invites"),
    ]

    operations = [
        migrations.AddField(
            model_name="tenantdatasetversion",
            name="source_name",
            field=models.CharField(blank=True, max_length=64, null=True),
        ),
        migrations.AddField(
            model_name="tenantdatasetversion",
            name="source_sha",
            field=models.CharField(blank=True, max_length=64, null=True),
        ),
        migrations.AddField(
            model_name="tenantdatasetversion",
            name="source_version",
            field=models.IntegerField(blank=True, null=True),
        ),
        migrations.CreateModel(
            name="DatasetLibraryVersion",
            fields=[
                (
                    "id",
                    models.UUIDField(editable=False, primary_key=True, serialize=False),
                ),
                ("pack", models.CharField(max_length=32)),
                ("dataset", models.CharField(max_length=64)),
                ("name", models.SlugField(max_length=64)),
                ("version", models.IntegerField()),
                ("files", models.JSONField()),
                ("sha256", models.CharField(max_length=64)),
                ("summary", models.JSONField(default=dict)),
                ("comment", models.TextField(blank=True, default="")),
                ("author", models.CharField(max_length=150)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "db_table": "dataset_library_version",
                "constraints": [
                    models.UniqueConstraint(
                        fields=("pack", "dataset", "name", "version"),
                        name="dataset_library_version_unique",
                    )
                ],
            },
        ),
    ]
