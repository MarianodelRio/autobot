"""Operation platform tables: no RLS by design (ADR-009), since the panel and the
operator commands need to read and write across tenants."""

import uuid

from django.db import models
from django.utils import timezone


class OpsAlert(models.Model):
    """One incident (ADR-031): one row per open period of a (kind, tenant). Its nature
    (condition or event) comes from the kind registry, `ops/incidents.py`; `auto_resolves`
    is True for a condition. The cases (sends, jobs, notices) are never copied here (this
    table has no RLS): they are computed live from their tables, and only their count and
    newest time are kept."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    kind = models.CharField(max_length=64, db_index=True)
    tenant_id = models.UUIDField(null=True, blank=True, db_index=True)  # no FK; purged, too
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
    # A review («Lo he revisado») closes an event: `resolved_by` is then the operator
    # (`auto`, `outage` and `info` are the platform's own closings).
    resolved_by = models.CharField(max_length=150, blank=True, default="")
    # Events: cases at or before it count as reviewed. A new open period inherits the
    # watermark of the latest row of the same (kind, tenant); with none, now - 24 h.
    review_watermark = models.DateTimeField(null=True, blank=True)
    case_count = models.PositiveIntegerField(default=0, db_default=0)
    last_case_at = models.DateTimeField(null=True, blank=True)
    # Kind-specific facts, NEVER personal data: the restart count seen, the month of a
    # billing incident, the error class.
    details = models.JSONField(default=dict, db_default={})

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
    tenant_id = models.UUIDField(null=True, blank=True, db_index=True)  # no FK; purged, too
    target_type = models.CharField(max_length=64, blank=True, default="")
    target_id = models.CharField(max_length=200, blank=True, default="")
    summary = models.TextField()
    details = models.JSONField(default=dict)

    class Meta:
        db_table = "audit_event"

    def __str__(self) -> str:
        return f"{self.action} {self.id}"


class PrivacySuppression(models.Model):
    """The suppression ledger (ADR-019): one row per erasure (`forget` of a contact,
    `purge` of a tenant), written in the same transaction as the erasure, so that
    `privacy_reapply` can erase again what a restored backup brings back. No PII: ids
    of the platform and keyed hashes (`runtime.suppressions.identity_hash`) only. No RLS
    (platform table, like audit_event), and not purged with a tenant: it is the proof
    that a tenant was erased."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    at = models.DateTimeField(default=timezone.now, db_index=True)
    kind = models.CharField(max_length=8)  # "forget" | "purge"
    tenant_id = models.UUIDField(db_index=True)  # no FK: the tenant may be gone
    contact_id = models.UUIDField(null=True, blank=True)
    channel = models.CharField(max_length=8, blank=True, default="")
    identity_hashes = models.JSONField(default=list)

    class Meta:
        db_table = "privacy_suppression"

    def __str__(self) -> str:
        return f"{self.kind} {self.id}"


class SystemSample(models.Model):
    taken_at = models.DateTimeField(default=timezone.now, db_index=True)
    cpu_pct = models.FloatField(null=True, blank=True)
    mem_used_pct = models.FloatField(null=True, blank=True)
    load1 = models.FloatField(null=True, blank=True)
    disk_used_pct = models.FloatField(null=True, blank=True)
    db_bytes = models.BigIntegerField()

    class Meta:
        db_table = "system_sample"

    def __str__(self) -> str:
        return f"system_sample {self.id} {self.taken_at}"
