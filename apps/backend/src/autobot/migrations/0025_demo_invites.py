"""Invitation codes for the demo doors (D5): `demo_invite` (created from the panel)
and `demo_access_grant` (written by the selector when a code is redeemed). Neither has
RLS, like `demo_session` (ADR-006 amendment)."""

import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("autobot", "0024_outbound_pending_idx"),
    ]

    operations = [
        migrations.CreateModel(
            name="DemoInvite",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid7,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("code", models.CharField(max_length=24, unique=True)),
                ("note", models.CharField(blank=True, default="", max_length=200)),
                ("max_uses", models.PositiveIntegerField(default=1)),
                ("uses", models.PositiveIntegerField(db_default=0, default=0)),
                ("expires_at", models.DateTimeField(blank=True, null=True)),
                ("revoked_at", models.DateTimeField(blank=True, null=True)),
                ("created_by", models.CharField(max_length=150)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "db_table": "demo_invite",
            },
        ),
        migrations.CreateModel(
            name="DemoAccessGrant",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid7,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                (
                    "channel",
                    models.CharField(
                        choices=[
                            ("main", "Main"),
                            ("demo_tg", "Demo Tg"),
                            ("demo_wa", "Demo Wa"),
                        ],
                        max_length=8,
                    ),
                ),
                ("external_id", models.CharField(max_length=160)),
                ("granted_at", models.DateTimeField()),
                ("expires_at", models.DateTimeField(blank=True, null=True)),
                (
                    "invite",
                    models.ForeignKey(
                        blank=True,
                        db_constraint=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to="autobot.demoinvite",
                    ),
                ),
            ],
            options={
                "db_table": "demo_access_grant",
                "constraints": [
                    models.UniqueConstraint(
                        fields=("channel", "external_id"),
                        name="demo_access_grant_channel_external_uniq",
                    )
                ],
            },
        ),
    ]
