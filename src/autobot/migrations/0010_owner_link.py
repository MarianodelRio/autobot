"""Adds `owner_link` and `owner_event`, the platform tables behind the owner's
notify bot (`docs/mejoras/02-avisos-y-resumenes.md` §5, §6; ADR-007).

Neither has RLS, on purpose (decision 2 of the proposal): a message arriving at the
notify bot's webhook carries only a Telegram chat id, and the tenant is found *from*
it, the same way `demo_event`/`demo_session` work for the demo doors (migration 0008,
ADR-006). `owner_link.chat_id` also moves the owner's chat out of `tenant.yaml` and
into the database: a personal datum that no longer needs to live in git, and whose
upkeep (connecting or disconnecting an owner) no longer needs a commit or a deploy.

Approved by the person on 2026-10-29 (see docs/adr/ADR-007-bot-de-duenos.md and
docs/mejoras/02-avisos-y-resumenes.md §10)."""

import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("autobot", "0009_metric_event"),
    ]

    operations = [
        migrations.CreateModel(
            name="OwnerLink",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid7, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("chat_id", models.BigIntegerField(blank=True, null=True)),
                ("linked_at", models.DateTimeField(blank=True, null=True)),
                (
                    "invite_hash",
                    models.CharField(blank=True, max_length=64, null=True, unique=True),
                ),
                ("invite_expires_at", models.DateTimeField(blank=True, null=True)),
                (
                    "tenant",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="+",
                        to="autobot.tenant",
                    ),
                ),
            ],
            options={"db_table": "owner_link"},
        ),
        migrations.AddIndex(
            model_name="ownerlink",
            index=models.Index(fields=["chat_id"], name="owner_link_chat_idx"),
        ),
        migrations.CreateModel(
            name="OwnerEvent",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid7, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("provider_event_id", models.CharField(max_length=200, unique=True)),
                ("payload", models.JSONField()),
                (
                    "status",
                    models.CharField(
                        choices=[("pending", "Pending"), ("done", "Done"), ("failed", "Failed")],
                        db_default="pending",
                        default="pending",
                        max_length=8,
                    ),
                ),
                ("received_at", models.DateTimeField()),
            ],
            options={"db_table": "owner_event"},
        ),
        migrations.AddIndex(
            model_name="ownerevent",
            index=models.Index(fields=["received_at"], name="owner_event_retention_idx"),
        ),
    ]
