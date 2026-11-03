"""Operation platform tables: no RLS by design (ADR-009), since the panel and the
operator commands need to read and write across tenants."""

import uuid

from django.db import models
from django.utils import timezone


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
