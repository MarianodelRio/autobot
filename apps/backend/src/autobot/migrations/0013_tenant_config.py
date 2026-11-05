"""Versioned tenant config and secrets (ADR-009): `tenant_document_version`,
`tenant_dataset_version`, `tenant_secret` and `config_revision`. No RLS by design: the
panel and the operator commands read and write across tenants, and `fp_app` only keeps
SELECT (autobot/db/grants.py).

Approved by the person on 2026-11-03 (see docs/arquitectura/adr/ADR-009-config-en-bd.md)."""

import django.db.models.deletion
from django.db import migrations, models

from autobot.db import grants as db_grants


def apply_grants(apps: object, schema_editor: object) -> None:
    db_grants.apply(schema_editor.connection)  # type: ignore[attr-defined]


class Migration(migrations.Migration):
    dependencies = [
        ("autobot", "0012_audit_event"),
    ]

    operations = [
        migrations.CreateModel(
            name="ConfigRevision",
            fields=[
                ("id", models.SmallIntegerField(primary_key=True, serialize=False)),
                ("revision", models.BigIntegerField(default=0)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "db_table": "config_revision",
            },
        ),
        migrations.CreateModel(
            name="TenantSecret",
            fields=[
                (
                    "tenant",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        primary_key=True,
                        serialize=False,
                        to="autobot.tenant",
                    ),
                ),
                (
                    "channel_type",
                    models.CharField(
                        choices=[("whatsapp", "whatsapp"), ("telegram", "telegram")],
                        max_length=10,
                    ),
                ),
                ("ciphertext", models.BinaryField()),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("updated_by", models.CharField(max_length=150)),
            ],
            options={
                "db_table": "tenant_secret",
            },
        ),
        migrations.CreateModel(
            name="TenantDatasetVersion",
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
                ("name", models.CharField(max_length=64)),
                ("version", models.IntegerField()),
                ("files", models.JSONField()),
                ("sha256", models.CharField(max_length=64)),
                ("comment", models.TextField(blank=True, default="")),
                ("author", models.CharField(max_length=150)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "tenant",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="+",
                        to="autobot.tenant",
                    ),
                ),
            ],
            options={
                "db_table": "tenant_dataset_version",
                "constraints": [
                    models.UniqueConstraint(
                        fields=("tenant", "name", "version"),
                        name="tenant_dataset_version_unique",
                    )
                ],
            },
        ),
        migrations.CreateModel(
            name="TenantDocumentVersion",
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
                ("version", models.IntegerField()),
                ("document", models.JSONField()),
                ("comment", models.TextField(blank=True, default="")),
                ("author", models.CharField(max_length=150)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "tenant",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="+",
                        to="autobot.tenant",
                    ),
                ),
            ],
            options={
                "db_table": "tenant_document_version",
                "constraints": [
                    models.UniqueConstraint(
                        fields=("tenant", "version"), name="tenant_doc_version_unique"
                    )
                ],
            },
        ),
        migrations.RunSQL(
            sql="INSERT INTO config_revision (id, revision, updated_at) VALUES (1, 0, now())",
            reverse_sql="DELETE FROM config_revision WHERE id = 1",
        ),
        migrations.RunPython(apply_grants, migrations.RunPython.noop),
    ]
