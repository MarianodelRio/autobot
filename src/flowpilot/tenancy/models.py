"""The `tenant` table: a mirror of tenants/*/tenant.yaml written by `sync_tenants`, for
foreign keys and RLS. Never edited by hand."""

from django.db import models


class Tenant(models.Model):
    class Status(models.TextChoices):
        ONBOARDING = "onboarding"
        ACTIVE = "active"
        PAUSED = "paused"
        OFFBOARDED = "offboarded"

    id = models.UUIDField(primary_key=True)  # fixed in tenant.yaml (UUIDv7)
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
