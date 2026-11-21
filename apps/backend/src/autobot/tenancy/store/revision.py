"""The configuration revision counter and the audited write of a document version."""

from django.utils import timezone

from autobot.ops import audit
from autobot.tenancy.models import ConfigRevision, Tenant, TenantDocumentVersion
from autobot.tenancy.registry import TenantSource


def bump(revision: ConfigRevision) -> None:
    revision.revision += 1
    revision.save(using="owner", update_fields=["revision", "updated_at"])


def write_document(
    source: TenantSource,
    revision: ConfigRevision,
    *,
    actor: str,
    comment: str,
    action: str,
    summary: str,
) -> int:
    doc = source.document
    tenant, _ = Tenant.objects.using("owner").update_or_create(
        pk=doc["id"],
        defaults={
            "slug": doc["slug"],
            "name": doc["name"],
            "pack": doc["pack"],
            "status": doc["status"],
            "timezone": doc["timezone"],
            "synced_at": timezone.now(),
        },
    )
    latest = (
        TenantDocumentVersion.objects.using("owner")
        .filter(tenant=tenant)
        .order_by("-version")
        .first()
    )
    version = latest.version + 1 if latest else 1
    TenantDocumentVersion.objects.using("owner").create(
        tenant=tenant,
        version=version,
        document=doc,
        author=actor,
        comment=comment,
    )
    bump(revision)
    audit.record_tenant(actor, action, tenant, summary, version=version, comment=comment)
    return version
