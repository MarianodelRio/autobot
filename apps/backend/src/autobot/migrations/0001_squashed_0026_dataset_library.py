"""Initial schema of the `autobot` app: the 26 migrations of the first months,
consolidated into one (no production database existed yet). It replaces them, so a
database that already applied all of them (a local development one) keeps working
untouched, and a fresh one runs this single migration.

Besides the models, it carries what a model cannot express:

1. Composite foreign keys `(tenant_id, x_id)`: a child row can only point to a parent
   of its own tenant (ADR-002).
2. Row level security, forced also for the table owner, on every table with `tenant_id`
   (and on `tenant`, over its own `id`): without `app.tenant_id` set, no row is visible.
   Each table also gets `readonly_all` for `fp_readonly`, the SQL console's "every
   client" mode.
3. `purge_platform_history(cutoff)`, a SECURITY DEFINER function (ADR-002, ADR-009).
4. The single `config_revision` row (ADR-009).
5. `autobot/db/grants.py`, applied last; deploy.sh and restore.sh reapply it afterwards.

Approved by the person (touches RLS and roles; there is no production database yet).
"""

import uuid
from typing import Any

import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models

from autobot.db import grants as db_grants

TENANT = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"

# (table, tenant column): every table with tenant data. The isolation test checks that no
# model with tenant_id is missing from here.
RLS_TABLES = [
    ("tenant", "id"),
    ("contact", "tenant_id"),
    ("conversation", "tenant_id"),
    ("inbound_event", "tenant_id"),
    ("outbound_message", "tenant_id"),
    ("notification", "tenant_id"),
    ("metric_event", "tenant_id"),
]

# (table, constraint, column, parent, on delete)
COMPOSITE_FKS = [
    ("conversation", "conversation_contact_fk", "contact_id", "contact", "CASCADE"),
    ("outbound_message", "outbound_message_contact_fk", "contact_id", "contact", "CASCADE"),
    # Events are deleted after 90 days and messages kept 12 months: only the event
    # column is cleared, never tenant_id.
    (
        "outbound_message",
        "outbound_message_inbound_event_fk",
        "inbound_event_id",
        "inbound_event",
        "SET NULL (inbound_event_id)",
    ),
    ("notification", "notification_contact_fk", "contact_id", "contact", "CASCADE"),
]

# Clamps the cutoff to at most a year ago, whatever the caller passes (`fp_app` has
# EXECUTE on it and `'infinity'` would otherwise erase everything).
PURGE_FUNCTION = """
CREATE FUNCTION purge_platform_history(cutoff timestamptz) RETURNS void
LANGUAGE sql SECURITY DEFINER SET search_path = public, pg_temp AS $$
    DELETE FROM ops_alert WHERE resolved_at < least(cutoff, now() - interval '1 year');
    DELETE FROM audit_event WHERE at < least(cutoff, now() - interval '1 year');
$$
"""


def composite_fk(
    table: str, name: str, column: str, parent: str, on_delete: str
) -> migrations.RunSQL:
    return migrations.RunSQL(
        sql=(
            f"ALTER TABLE {table} ADD CONSTRAINT {name} FOREIGN KEY (tenant_id, {column})"
            f" REFERENCES {parent} (tenant_id, id) ON DELETE {on_delete}"
        ),
        reverse_sql=f"ALTER TABLE {table} DROP CONSTRAINT {name}",
    )


def rls(table: str, column: str) -> migrations.RunSQL:
    check = f"{column} = {TENANT}"
    return migrations.RunSQL(
        sql=[
            f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY",
            f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY",
            f"CREATE POLICY tenant_isolation ON {table} USING ({check}) WITH CHECK ({check})",
            f"CREATE POLICY readonly_all ON {table} FOR SELECT TO fp_readonly"
            " USING (current_setting('app.readonly_all', true) = 'on')",
        ],
        reverse_sql=[
            f"DROP POLICY readonly_all ON {table}",
            f"DROP POLICY tenant_isolation ON {table}",
            f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY",
            f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY",
        ],
    )


def apply_grants(apps: Any, schema_editor: Any) -> None:
    db_grants.apply(schema_editor.connection)


class Migration(migrations.Migration):
    initial = True

    replaces = [
        ("autobot", "0001_initial"),
        ("autobot", "0002_tenant_isolation"),
        ("autobot", "0003_notification_audience"),
        ("autobot", "0004_inbound_effect_state"),
        ("autobot", "0005_platformcache"),
        ("autobot", "0006_outbound_unknown_at"),
        ("autobot", "0007_retention_indexes"),
        ("autobot", "0008_demo_channels"),
        ("autobot", "0009_metric_event"),
        ("autobot", "0010_owner_link"),
        ("autobot", "0011_apply_grants"),
        ("autobot", "0012_audit_event"),
        ("autobot", "0013_tenant_config"),
        ("autobot", "0014_outbound_sent_index"),
        ("autobot", "0015_ops_alert"),
        ("autobot", "0016_system_sample"),
        ("autobot", "0017_auth_db_grants"),
        ("autobot", "0018_savedquery"),
        ("autobot", "0019_readonly_all"),
        ("autobot", "0020_delete_savedquery"),
        ("autobot", "0021_purge_platform_history_min_cutoff"),
        ("autobot", "0022_notification_contact"),
        ("autobot", "0023_notification_contact_fk"),
        ("autobot", "0024_outbound_pending_idx"),
        ("autobot", "0025_demo_invites"),
        ("autobot", "0026_dataset_library"),
    ]

    dependencies = [
        # `apply_grants` below must see auth's and sessions' tables already created.
        ("auth", "0012_alter_user_first_name_max_length"),
        ("sessions", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="AuditEvent",
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
                    "at",
                    models.DateTimeField(db_index=True, default=django.utils.timezone.now),
                ),
                ("actor", models.CharField(max_length=150)),
                ("action", models.CharField(db_index=True, max_length=64)),
                ("tenant_id", models.UUIDField(blank=True, db_index=True, null=True)),
                (
                    "target_type",
                    models.CharField(blank=True, default="", max_length=64),
                ),
                ("target_id", models.CharField(blank=True, default="", max_length=200)),
                ("summary", models.TextField()),
                ("details", models.JSONField(default=dict)),
            ],
            options={
                "db_table": "audit_event",
            },
        ),
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
            name="Tenant",
            fields=[
                ("id", models.UUIDField(primary_key=True, serialize=False)),
                ("slug", models.SlugField(max_length=64, unique=True)),
                ("name", models.CharField(max_length=200)),
                ("pack", models.CharField(max_length=32)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("onboarding", "Onboarding"),
                            ("active", "Active"),
                            ("paused", "Paused"),
                            ("offboarded", "Offboarded"),
                        ],
                        max_length=16,
                    ),
                ),
                ("timezone", models.CharField(max_length=64)),
                ("synced_at", models.DateTimeField()),
            ],
            options={
                "db_table": "tenant",
            },
        ),
        migrations.CreateModel(
            name="Contact",
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
                    "tenant",
                    models.ForeignKey(
                        db_index=False,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="+",
                        to="autobot.tenant",
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
                ("phone_e164", models.CharField(blank=True, max_length=16, null=True)),
                (
                    "display_name",
                    models.CharField(blank=True, db_default="", default="", max_length=200),
                ),
                ("opt_out", models.BooleanField(db_default=False, default=False)),
                ("opt_out_at", models.DateTimeField(blank=True, null=True)),
                ("unreachable", models.BooleanField(db_default=False, default=False)),
                ("last_activity_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "db_table": "contact",
            },
        ),
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
            name="PlatformCache",
            fields=[
                (
                    "cache_key",
                    models.CharField(max_length=255, primary_key=True, serialize=False),
                ),
                ("value", models.TextField()),
                ("expires", models.DateTimeField(db_index=True)),
            ],
            options={
                "db_table": "platform_cache",
            },
        ),
        migrations.CreateModel(
            name="SystemSample",
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
                (
                    "taken_at",
                    models.DateTimeField(db_index=True, default=django.utils.timezone.now),
                ),
                ("cpu_pct", models.FloatField(blank=True, null=True)),
                ("mem_used_pct", models.FloatField(blank=True, null=True)),
                ("load1", models.FloatField(blank=True, null=True)),
                ("disk_used_pct", models.FloatField(blank=True, null=True)),
                ("db_bytes", models.BigIntegerField()),
            ],
            options={
                "db_table": "system_sample",
            },
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
        migrations.CreateModel(
            name="DemoEvent",
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
                ("provider_event_id", models.CharField(max_length=200)),
                ("payload", models.JSONField()),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "Pending"),
                            ("done", "Done"),
                            ("failed", "Failed"),
                        ],
                        db_default="pending",
                        default="pending",
                        max_length=8,
                    ),
                ),
                ("received_at", models.DateTimeField()),
            ],
            options={
                "db_table": "demo_event",
                "indexes": [models.Index(fields=["received_at"], name="demo_event_retention_idx")],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("channel", "provider_event_id"),
                        name="demo_event_provider_uniq",
                    )
                ],
            },
        ),
        migrations.CreateModel(
            name="OpsAlert",
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
                ("kind", models.CharField(db_index=True, max_length=64)),
                ("tenant_id", models.UUIDField(blank=True, db_index=True, null=True)),
                ("severity", models.CharField(max_length=16)),
                ("text", models.TextField()),
                (
                    "first_seen_at",
                    models.DateTimeField(default=django.utils.timezone.now),
                ),
                (
                    "last_seen_at",
                    models.DateTimeField(default=django.utils.timezone.now),
                ),
                ("occurrences", models.PositiveIntegerField(default=1)),
                ("sent_count", models.PositiveIntegerField(default=0)),
                ("last_sent_at", models.DateTimeField(blank=True, null=True)),
                (
                    "last_delivery",
                    models.CharField(blank=True, default="", max_length=16),
                ),
                ("auto_resolves", models.BooleanField(default=True)),
                ("resolved_at", models.DateTimeField(blank=True, null=True)),
                (
                    "resolved_by",
                    models.CharField(blank=True, default="", max_length=150),
                ),
            ],
            options={
                "db_table": "ops_alert",
                "constraints": [
                    models.UniqueConstraint(
                        condition=models.Q(("resolved_at__isnull", True)),
                        fields=("kind", "tenant_id"),
                        name="ops_alert_one_open",
                        nulls_distinct=False,
                    )
                ],
            },
        ),
        migrations.CreateModel(
            name="OwnerEvent",
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
                ("provider_event_id", models.CharField(max_length=200, unique=True)),
                ("payload", models.JSONField()),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "Pending"),
                            ("done", "Done"),
                            ("failed", "Failed"),
                        ],
                        db_default="pending",
                        default="pending",
                        max_length=8,
                    ),
                ),
                ("received_at", models.DateTimeField()),
            ],
            options={
                "db_table": "owner_event",
                "indexes": [models.Index(fields=["received_at"], name="owner_event_retention_idx")],
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
            name="InboundEvent",
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
                (
                    "kind",
                    models.CharField(
                        choices=[("message", "Message"), ("status", "Status")],
                        max_length=8,
                    ),
                ),
                ("provider_event_id", models.CharField(max_length=200)),
                ("payload", models.JSONField(null=True)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "Pending"),
                            ("done", "Done"),
                            ("failed", "Failed"),
                            ("ignored", "Ignored"),
                        ],
                        max_length=8,
                    ),
                ),
                ("error", models.TextField(blank=True, db_default="", default="")),
                ("received_at", models.DateTimeField()),
                ("processed_at", models.DateTimeField(blank=True, null=True)),
                (
                    "tenant",
                    models.ForeignKey(
                        db_index=False,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="+",
                        to="autobot.tenant",
                    ),
                ),
                ("effect_state", models.JSONField(db_default={}, default=dict)),
            ],
            options={
                "db_table": "inbound_event",
            },
        ),
        migrations.CreateModel(
            name="DemoSession",
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
                ("selected_at", models.DateTimeField()),
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
                "db_table": "demo_session",
            },
        ),
        migrations.CreateModel(
            name="Conversation",
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
                ("state", models.JSONField(default=dict)),
                ("state_version", models.IntegerField(blank=True, null=True)),
                ("last_inbound_at", models.DateTimeField(blank=True, null=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "contact",
                    models.ForeignKey(
                        db_constraint=False,
                        db_index=False,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="+",
                        to="autobot.contact",
                    ),
                ),
                (
                    "tenant",
                    models.ForeignKey(
                        db_index=False,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="+",
                        to="autobot.tenant",
                    ),
                ),
            ],
            options={
                "db_table": "conversation",
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
                ("source_name", models.CharField(blank=True, max_length=64, null=True)),
                ("source_sha", models.CharField(blank=True, max_length=64, null=True)),
                ("source_version", models.IntegerField(blank=True, null=True)),
            ],
            options={
                "db_table": "tenant_dataset_version",
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
        migrations.CreateModel(
            name="OwnerLink",
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
            options={
                "db_table": "owner_link",
                "indexes": [models.Index(fields=["chat_id"], name="owner_link_chat_idx")],
            },
        ),
        migrations.CreateModel(
            name="OutboundMessage",
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
                ("idem_key", models.TextField()),
                ("seq", models.IntegerField(db_default=0, default=0)),
                (
                    "kind",
                    models.CharField(
                        choices=[("reply", "Reply"), ("proactive", "Proactive")],
                        max_length=10,
                    ),
                ),
                ("payload", models.JSONField(null=True)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "Pending"),
                            ("sending", "Sending"),
                            ("sent", "Sent"),
                            ("failed", "Failed"),
                            ("unknown", "Unknown"),
                        ],
                        db_default="pending",
                        default="pending",
                        max_length=8,
                    ),
                ),
                ("attempts", models.IntegerField(db_default=0, default=0)),
                (
                    "provider_message_id",
                    models.CharField(blank=True, max_length=200, null=True),
                ),
                (
                    "pricing_category",
                    models.CharField(blank=True, max_length=32, null=True),
                ),
                ("billable", models.BooleanField(null=True)),
                ("last_error", models.TextField(blank=True, db_default="", default="")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("sent_at", models.DateTimeField(blank=True, null=True)),
                (
                    "contact",
                    models.ForeignKey(
                        db_constraint=False,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="+",
                        to="autobot.contact",
                    ),
                ),
                (
                    "inbound_event",
                    models.ForeignKey(
                        blank=True,
                        db_constraint=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to="autobot.inboundevent",
                    ),
                ),
                (
                    "tenant",
                    models.ForeignKey(
                        db_index=False,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="+",
                        to="autobot.tenant",
                    ),
                ),
                ("unknown_at", models.DateTimeField(blank=True, null=True)),
            ],
            options={
                "db_table": "outbound_message",
                "indexes": [
                    models.Index(fields=["tenant", "created_at"], name="outbound_retention_idx"),
                    models.Index(fields=["tenant", "sent_at"], name="outbound_sent_idx"),
                    models.Index(
                        condition=models.Q(("status", "unknown")),
                        fields=["tenant", "unknown_at"],
                        name="outbound_unknown_idx",
                    ),
                    models.Index(
                        condition=models.Q(("status", "pending")),
                        fields=["tenant", "created_at"],
                        name="outbound_pending_idx",
                    ),
                    models.Index(
                        fields=["tenant", "provider_message_id"],
                        name="outbound_provider_id_idx",
                    ),
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("tenant", "idem_key"), name="outbound_idem_key_uniq"
                    )
                ],
            },
        ),
        migrations.CreateModel(
            name="Notification",
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
                ("idem_key", models.TextField()),
                ("kind", models.CharField(max_length=64)),
                ("text", models.TextField()),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "Pending"),
                            ("sent", "Sent"),
                            ("failed", "Failed"),
                        ],
                        db_default="pending",
                        default="pending",
                        max_length=8,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("sent_at", models.DateTimeField(blank=True, null=True)),
                (
                    "tenant",
                    models.ForeignKey(
                        db_index=False,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="+",
                        to="autobot.tenant",
                    ),
                ),
                (
                    "audience",
                    models.CharField(
                        choices=[("owner", "Owner")],
                        db_default="owner",
                        default="owner",
                        max_length=8,
                    ),
                ),
                (
                    "contact",
                    models.ForeignKey(
                        blank=True,
                        db_constraint=False,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="+",
                        to="autobot.contact",
                    ),
                ),
            ],
            options={
                "db_table": "notification",
                "indexes": [
                    models.Index(
                        fields=["tenant", "created_at"],
                        name="notification_retention_idx",
                    )
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("tenant", "idem_key"), name="notification_idem_key_uniq"
                    )
                ],
            },
        ),
        migrations.CreateModel(
            name="MetricEvent",
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
                ("kind", models.CharField(max_length=64)),
                ("value", models.DecimalField(decimal_places=2, max_digits=12)),
                ("idem_key", models.TextField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "tenant",
                    models.ForeignKey(
                        db_index=False,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="+",
                        to="autobot.tenant",
                    ),
                ),
            ],
            options={
                "db_table": "metric_event",
                "indexes": [
                    models.Index(
                        fields=["tenant", "kind", "created_at"],
                        name="metric_event_kind_idx",
                    )
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("tenant", "idem_key"), name="metric_event_idem_key_uniq"
                    )
                ],
            },
        ),
        migrations.AddIndex(
            model_name="inboundevent",
            index=models.Index(fields=["tenant", "received_at"], name="inbound_retention_idx"),
        ),
        migrations.AddConstraint(
            model_name="inboundevent",
            constraint=models.UniqueConstraint(
                fields=("tenant", "id"), name="inbound_event_tenant_id_uniq"
            ),
        ),
        migrations.AddConstraint(
            model_name="inboundevent",
            constraint=models.UniqueConstraint(
                fields=("tenant", "channel", "provider_event_id"),
                name="inbound_event_provider_uniq",
            ),
        ),
        migrations.AddIndex(
            model_name="demosession",
            index=models.Index(fields=["selected_at"], name="demo_session_retention_idx"),
        ),
        migrations.AddConstraint(
            model_name="demosession",
            constraint=models.UniqueConstraint(
                fields=("channel", "external_id"),
                name="demo_session_channel_external_uniq",
            ),
        ),
        migrations.AddConstraint(
            model_name="conversation",
            constraint=models.UniqueConstraint(
                fields=("tenant", "contact"), name="conversation_contact_uniq"
            ),
        ),
        migrations.AddIndex(
            model_name="contact",
            index=models.Index(
                fields=["tenant", "last_activity_at", "created_at"],
                name="contact_retention_idx",
            ),
        ),
        migrations.AddConstraint(
            model_name="contact",
            constraint=models.UniqueConstraint(
                fields=("tenant", "id"), name="contact_tenant_id_uniq"
            ),
        ),
        migrations.AddConstraint(
            model_name="contact",
            constraint=models.UniqueConstraint(
                fields=("tenant", "channel", "external_id"),
                name="contact_external_id_uniq",
            ),
        ),
        migrations.AddConstraint(
            model_name="tenantdatasetversion",
            constraint=models.UniqueConstraint(
                fields=("tenant", "name", "version"),
                name="tenant_dataset_version_unique",
            ),
        ),
        migrations.AddConstraint(
            model_name="tenantdocumentversion",
            constraint=models.UniqueConstraint(
                fields=("tenant", "version"), name="tenant_doc_version_unique"
            ),
        ),
        *(composite_fk(*fk) for fk in COMPOSITE_FKS),
        *(rls(table, column) for table, column in RLS_TABLES),
        # The tenant mirror is written as fp_owner; fp_app just reads it.
        migrations.RunSQL(
            sql="REVOKE INSERT, UPDATE, DELETE ON tenant FROM fp_app",
            reverse_sql="GRANT INSERT, UPDATE, DELETE ON tenant TO fp_app",
        ),
        migrations.RunSQL(
            sql=PURGE_FUNCTION,
            reverse_sql="DROP FUNCTION purge_platform_history(timestamptz)",
        ),
        migrations.RunSQL(
            sql="INSERT INTO config_revision (id, revision, updated_at) VALUES (1, 0, now())",
            reverse_sql="DELETE FROM config_revision WHERE id = 1",
        ),
        migrations.RunPython(apply_grants, migrations.RunPython.noop),
    ]
