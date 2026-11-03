"""Operation platform tables: no RLS by design (ADR-009), since the panel and the
operator commands need to read and write across tenants."""

import uuid

from django.db import models
from django.utils import timezone


class OpsAlert(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    kind = models.CharField(max_length=64, db_index=True)
    tenant_id = models.UUIDField(null=True, blank=True, db_index=True)  # no FK: survives purge
    severity = models.CharField(max_length=16)
    text = models.TextField()
    first_seen_at = models.DateTimeField(default=timezone.now)
    last_seen_at = models.DateTimeField(default=timezone.now)
    occurrences = models.PositiveIntegerField(default=1)
    sent_count = models.PositiveIntegerField(default=0)
    last_sent_at = models.DateTimeField(null=True, blank=True)
    last_delivery = models.CharField(max_length=16, blank=True, default="")
    auto_resolves = models.BooleanField(default=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.CharField(max_length=150, blank=True, default="")

    class Meta:
        db_table = "ops_alert"
        constraints = [
            models.UniqueConstraint(
                fields=["kind", "tenant_id"],
                condition=models.Q(resolved_at__isnull=True),
                name="ops_alert_one_open",
                nulls_distinct=False,
            )
        ]

    def __str__(self) -> str:
        return f"{self.kind} {self.id}"


class AuditEvent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    at = models.DateTimeField(default=timezone.now, db_index=True)
    actor = models.CharField(max_length=150)
    action = models.CharField(max_length=64, db_index=True)
    tenant_id = models.UUIDField(null=True, blank=True, db_index=True)  # no FK: survives purge
    target_type = models.CharField(max_length=64, blank=True, default="")
    target_id = models.CharField(max_length=200, blank=True, default="")
    summary = models.TextField()
    details = models.JSONField(default=dict)

    class Meta:
        db_table = "audit_event"

    def __str__(self) -> str:
        return f"{self.action} {self.id}"
