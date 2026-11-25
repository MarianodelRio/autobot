"""The `tenant` table: a mirror of the current document version, for foreign keys and
RLS. Written only by `autobot.tenancy.store` (ADR-009)."""

from django.db import models


class Tenant(models.Model):
    class Status(models.TextChoices):
        ONBOARDING = "onboarding"
        ACTIVE = "active"
        PAUSED = "paused"
        OFFBOARDED = "offboarded"

    id = models.UUIDField(primary_key=True)  # fixed at creation (UUIDv7)
    slug = models.SlugField(max_length=64, unique=True)
    name = models.CharField(max_length=200)
    pack = models.CharField(max_length=32)
    status = models.CharField(max_length=16, choices=Status)
    timezone = models.CharField(max_length=64)
    synced_at = models.DateTimeField()

    class Meta:
        db_table = "tenant"

    def __str__(self) -> str:
        return self.slug


class TenantDocumentVersion(models.Model):
    """An immutable version of a tenant's document (ADR-009): no RLS, since the panel
    and the operator commands read and write across tenants. `fp_app` has no access."""

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="+")
    version = models.IntegerField()
    document = models.JSONField()  # the full TenantDocument, without secrets
    comment = models.TextField(blank=True, default="")
    author = models.CharField(max_length=150)  # a panel user, or "command:<name>"
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "tenant_document_version"
        constraints = [
            models.UniqueConstraint(fields=["tenant", "version"], name="tenant_doc_version_unique")
        ]

    def __str__(self) -> str:
        return f"{self.tenant_id} v{self.version}"


class TenantDatasetVersion(models.Model):
    """An immutable version of one of a tenant's datasets (ADR-009), e.g. `bus`'s
    timetable. No RLS, same reasons as `TenantDocumentVersion`.

    `source_name`/`source_version`/`source_sha` (ADR-013) record which library entry
    this was copied from, when it was: plain columns, no FK, since the library entry
    may later change version or be deleted without affecting this copy."""

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="+")
    name = models.CharField(max_length=64)  # "timetable"
    version = models.IntegerField()
    files = models.JSONField()  # {"path/within/the/dataset": "<UTF-8 text>", ...}
    sha256 = models.CharField(max_length=64)  # of json.dumps(files, sort_keys=True)
    comment = models.TextField(blank=True, default="")
    author = models.CharField(max_length=150)
    created_at = models.DateTimeField(auto_now_add=True)
    source_name = models.CharField(max_length=64, null=True, blank=True)  # noqa: DJ001
    source_version = models.IntegerField(null=True, blank=True)
    source_sha = models.CharField(max_length=64, null=True, blank=True)  # noqa: DJ001

    class Meta:
        db_table = "tenant_dataset_version"
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "name", "version"], name="tenant_dataset_version_unique"
            )
        ]

    def __str__(self) -> str:
        return f"{self.tenant_id} {self.name} v{self.version}"


class DatasetLibraryVersion(models.Model):
    """An immutable version of a named, reusable dataset in the operator's library
    (ADR-013): uploaded once by terminal, independent of any tenant, and copied into
    `TenantDatasetVersion` when a client chooses or applies it. No `tenant_id`, no RLS:
    it is platform configuration, not customer data."""

    id = models.UUIDField(primary_key=True, editable=False)
    pack = models.CharField(max_length=32)
    dataset = models.CharField(max_length=64)  # "timetable"
    name = models.SlugField(max_length=64)  # chosen at upload time, e.g. "linea-cordoba"
    version = models.IntegerField()
    files = models.JSONField()  # {"path/within/the/dataset": "<UTF-8 text>", ...}
    sha256 = models.CharField(max_length=64)  # of json.dumps(files, sort_keys=True)
    summary = models.JSONField(default=dict)  # Pack.dataset_summary's own result
    comment = models.TextField(blank=True, default="")
    author = models.CharField(max_length=150)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "dataset_library_version"
        constraints = [
            models.UniqueConstraint(
                fields=["pack", "dataset", "name", "version"],
                name="dataset_library_version_unique",
            )
        ]

    def __str__(self) -> str:
        return f"{self.pack}/{self.dataset}/{self.name} v{self.version}"


class TenantSecret(models.Model):
    """A tenant's channel secrets, Fernet-encrypted (ADR-009). No RLS; `fp_app` has no
    access and `fp_readonly` cannot read it (SENSITIVE_TABLES, autobot/db/grants.py)."""

    tenant = models.OneToOneField(Tenant, on_delete=models.CASCADE, primary_key=True)
    channel_type = models.CharField(
        max_length=10, choices=[("whatsapp", "whatsapp"), ("telegram", "telegram")]
    )
    ciphertext = models.BinaryField()  # a Fernet token of the secrets' JSON
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.CharField(max_length=150)

    class Meta:
        db_table = "tenant_secret"

    def __str__(self) -> str:
        return f"{self.tenant_id} {self.channel_type}"


class ConfigRevision(models.Model):
    """A single row: the global counter every config write increments, so each process
    knows when to reload its registry (ADR-009). No tenant_id, no RLS."""

    id = models.SmallIntegerField(primary_key=True)
    revision = models.BigIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "config_revision"

    def __str__(self) -> str:
        return f"revision {self.revision}"


class ConfigFollower(models.Model):
    """One row per live process (a gunicorn worker or a queue worker): the configuration
    revision it has loaded, refreshed by its registry refresher (ADR-030). It lets the
    panel say «applied in N processes» after a save and lets `ops_check` alert on a process
    that stays behind. Platform operation data: no tenant_id, no RLS. Rows are only
    meaningful while recent (`seen_at`); a dead process's row is ignored and later purged."""

    service = models.CharField(max_length=64)  # SERVICE_NAME: web, web-panel, worker-...
    host = models.CharField(max_length=128)  # the container's hostname
    pid = models.IntegerField()
    revision = models.BigIntegerField()  # the config revision the process has loaded
    started_at = models.DateTimeField()
    seen_at = models.DateTimeField(db_index=True)

    class Meta:
        db_table = "config_follower"
        constraints = [
            models.UniqueConstraint(fields=["host", "pid"], name="config_follower_host_pid")
        ]

    def __str__(self) -> str:
        return f"{self.service} {self.host}:{self.pid} r{self.revision}"
