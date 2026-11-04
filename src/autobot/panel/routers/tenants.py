"""Tenant reads: ficha, history, datasets, secrets status, activation, summary,
notifications and on-demand health (DESIGN §6.4; T16a)."""

from django.http import HttpRequest
from django.utils import timezone
from ninja import Router

from autobot.panel.services import tenants as service
from autobot.panel.services.overview import TenantRow, tenant_rows

router = Router(tags=["tenants"])


@router.get("/tenants", response=list[TenantRow])
def list_tenants(request: HttpRequest) -> list[TenantRow]:
    return tenant_rows(timezone.now())


@router.get("/tenants/{slug}", response=service.TenantDetail)
def tenant_detail(request: HttpRequest, slug: str) -> service.TenantDetail:
    return service.tenant_detail(slug)


@router.get("/tenants/{slug}/versions", response=list[service.VersionSummary])
def tenant_versions(request: HttpRequest, slug: str) -> list[service.VersionSummary]:
    return service.tenant_versions(slug)


@router.get("/tenants/{slug}/versions/{version}", response=service.VersionDetail)
def tenant_version(request: HttpRequest, slug: str, version: int) -> service.VersionDetail:
    return service.tenant_version(slug, version)


@router.get("/tenants/{slug}/datasets", response=list[service.DatasetVersionOut])
def tenant_datasets(request: HttpRequest, slug: str) -> list[service.DatasetVersionOut]:
    return service.tenant_datasets(slug)


@router.get("/tenants/{slug}/secrets", response=service.SecretsStatus)
def tenant_secrets(request: HttpRequest, slug: str) -> service.SecretsStatus:
    return service.tenant_secrets(slug)


@router.get("/tenants/{slug}/activation-checklist", response=list[service.ChecklistItemOut])
def tenant_checklist(request: HttpRequest, slug: str) -> list[service.ChecklistItemOut]:
    return service.tenant_checklist(slug)


@router.get("/tenants/{slug}/summary", response=service.SummaryOut)
def tenant_summary(request: HttpRequest, slug: str) -> service.SummaryOut:
    return service.tenant_summary(slug)


@router.get("/tenants/{slug}/notifications", response=list[service.NotificationOut])
def tenant_notifications(request: HttpRequest, slug: str) -> list[service.NotificationOut]:
    return service.tenant_notifications(slug)


@router.post("/tenants/{slug}/health-check", response=list[service.HealthIssueOut])
def tenant_health_check(request: HttpRequest, slug: str) -> list[service.HealthIssueOut]:
    return service.tenant_health_check(slug)
