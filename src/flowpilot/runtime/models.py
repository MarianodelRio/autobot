"""Runtime tables (design.md §12.1).

Every table with `tenant_id` has RLS (migration 0002). Children point to their parent
through a composite foreign key `(tenant_id, x_id) → x(tenant_id, id)`, so a row can never
reference another tenant's row. Django has no composite foreign keys: the relation is a
`ForeignKey(db_constraint=False)` for the ORM and the constraint is created in SQL.
"""

import uuid

from django.db import models

from flowpilot.tenancy.models import Tenant


class Channel(models.TextChoices):
    MAIN = "main"
    TEST = "test"


class TenantScoped(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    # No index of its own: every table has a unique constraint starting with tenant_id.
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="+", db_index=False)

    class Meta:
        abstract = True

    def __str__(self) -> str:
        # Only the id: rows hold personal data that must not leak into logs or the Admin.
        return f"{self._meta.model_name} {self.id}"


def _tenant_and_id(table: str) -> models.UniqueConstraint:
    return models.UniqueConstraint(fields=["tenant", "id"], name=f"{table}_tenant_id_uniq")


class Contact(TenantScoped):
    channel = models.CharField(max_length=8, choices=Channel)
    external_id = models.CharField(max_length=160)  # BSUID, phone or Telegram id
    phone_e164 = models.CharField(max_length=16, null=True, blank=True)  # noqa: DJ001 (§12.1: NULL = unknown)
    display_name = models.CharField(max_length=200, blank=True, default="", db_default="")
    opt_out = models.BooleanField(default=False, db_default=False)
    opt_out_at = models.DateTimeField(null=True, blank=True)
    unreachable = models.BooleanField(default=False, db_default=False)
    last_activity_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "contact"
        constraints = [
            _tenant_and_id("contact"),
            models.UniqueConstraint(
                fields=["tenant", "channel", "external_id"], name="contact_external_id_uniq"
            ),
        ]


class Conversation(TenantScoped):
    contact = models.ForeignKey(
        Contact, on_delete=models.CASCADE, db_constraint=False, db_index=False, related_name="+"
    )  # covered by UNIQUE(tenant_id, contact_id)
    state = models.JSONField(default=dict)
    state_version = models.IntegerField(null=True, blank=True)
    last_inbound_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "conversation"
        constraints = [
            models.UniqueConstraint(fields=["tenant", "contact"], name="conversation_contact_uniq"),
        ]


class InboundEvent(TenantScoped):
    class Kind(models.TextChoices):
        MESSAGE = "message"
        STATUS = "status"

    class Status(models.TextChoices):
        PENDING = "pending"
        DONE = "done"
        FAILED = "failed"
        IGNORED = "ignored"

    channel = models.CharField(max_length=8, choices=Channel)
    kind = models.CharField(max_length=8, choices=Kind)
    provider_event_id = models.CharField(max_length=200)
    payload = models.JSONField(null=True)  # emptied after 30 days (§12.3)
    status = models.CharField(max_length=8, choices=Status)
    error = models.TextField(blank=True, default="", db_default="")
    received_at = models.DateTimeField()
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "inbound_event"
        constraints = [
            _tenant_and_id("inbound_event"),
            models.UniqueConstraint(
                fields=["tenant", "channel", "provider_event_id"],
                name="inbound_event_provider_uniq",
            ),
        ]


class OutboundMessage(TenantScoped):
    class Kind(models.TextChoices):
        REPLY = "reply"
        PROACTIVE = "proactive"

    class Status(models.TextChoices):
        PENDING = "pending"
        SENDING = "sending"
        SENT = "sent"
        FAILED = "failed"
        UNKNOWN = "unknown"

    contact = models.ForeignKey(
        Contact, on_delete=models.CASCADE, db_constraint=False, related_name="+"
    )
    channel = models.CharField(max_length=8, choices=Channel)
    idem_key = models.TextField()  # may hold a gcal_id (up to 1,024 characters)
    seq = models.IntegerField(default=0, db_default=0)
    kind = models.CharField(max_length=10, choices=Kind)
    payload = models.JSONField(null=True)  # common Reply/ProactiveMessage; emptied after 30 days
    status = models.CharField(
        max_length=8, choices=Status, default=Status.PENDING, db_default=Status.PENDING
    )
    attempts = models.IntegerField(default=0, db_default=0)
    # NULL until the provider answers (§12.1)
    provider_message_id = models.CharField(max_length=200, null=True, blank=True)  # noqa: DJ001
    pricing_category = models.CharField(max_length=32, null=True, blank=True)  # noqa: DJ001
    billable = models.BooleanField(null=True)
    last_error = models.TextField(blank=True, default="", db_default="")
    inbound_event = models.ForeignKey(
        InboundEvent,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_constraint=False,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "outbound_message"
        constraints = [
            models.UniqueConstraint(fields=["tenant", "idem_key"], name="outbound_idem_key_uniq"),
        ]
        indexes = [
            # apply_status looks a message up by the provider id (§7.2)
            models.Index(fields=["tenant", "provider_message_id"], name="outbound_provider_id_idx"),
        ]


class Notification(TenantScoped):
    class Status(models.TextChoices):
        PENDING = "pending"
        SENT = "sent"
        FAILED = "failed"

    idem_key = models.TextField()
    kind = models.CharField(max_length=64)
    text = models.TextField()
    status = models.CharField(
        max_length=8, choices=Status, default=Status.PENDING, db_default=Status.PENDING
    )
    created_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "notification"
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "idem_key"], name="notification_idem_key_uniq"
            ),
        ]


# ── Test bot tables: platform-level, no tenant_id and no RLS (§6.5, §12.1) ──


class TestBotEvent(models.Model):
    __test__ = False  # not a pytest test class

    class Status(models.TextChoices):
        PENDING = "pending"
        DONE = "done"
        FAILED = "failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    update_id = models.BigIntegerField(unique=True)
    payload = models.JSONField()
    status = models.CharField(
        max_length=8, choices=Status, default=Status.PENDING, db_default=Status.PENDING
    )
    received_at = models.DateTimeField()

    class Meta:
        db_table = "test_bot_event"

    def __str__(self) -> str:
        return f"test_bot_event {self.update_id}"


class TestSession(models.Model):
    __test__ = False  # not a pytest test class

    telegram_user_id = models.BigIntegerField(primary_key=True)
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="+")
    selected_at = models.DateTimeField()

    class Meta:
        db_table = "test_session"

    def __str__(self) -> str:
        return f"test_session {self.tenant_id}"  # never the Telegram user id
