"""Tenant reads: ficha, history, datasets, secrets status, activation, summary,
notifications and on-demand health."""

from typing import Any, Literal, cast

from django.http import HttpRequest
from django.utils import timezone
from ninja import Router, Schema

from autobot.panel.services import tenants as service
from autobot.panel.services.overview import TenantRow, tenant_rows
from autobot.tenancy import store
from autobot.tenancy.models import Tenant

router = Router(tags=["tenants"])


class CreateTenantIn(Schema):
    pack: str
    slug: str
    name: str
    timezone: str
    channel_type: Literal["whatsapp", "telegram"] | None = None
    demo_description: str | None = None
    config: dict[str, Any]
    comment: str = ""


class DocumentIn(Schema):
    document: dict[str, Any]
    base_version: int
    comment: str = ""


class RollbackIn(Schema):
    version: int
    comment: str


class StatusIn(Schema):
    action: str
    confirm_slug: str | None = None


class SecretsIn(Schema):
    secrets: dict[str, str]


class DeleteTenantIn(Schema):
    confirm_slug: str


class VersionOut(Schema):
    version: int


class SlugAvailability(Schema):
    available: bool


@router.get("/tenant-slug-availability", response=SlugAvailability)
def tenant_slug_availability(request: HttpRequest, slug: str) -> SlugAvailability:
    return SlugAvailability(available=not Tenant.objects.using("owner").filter(slug=slug).exists())


@router.post("/tenants", response=VersionOut)
def create_tenant(request: HttpRequest, payload: CreateTenantIn) -> VersionOut:
    doc = store.new_document(**payload.model_dump(exclude={"comment"}))
    return VersionOut(
        version=store.create_tenant(
            document=doc, actor=request.user.username, comment=payload.comment
        )
    )


@router.put("/tenants/{slug}/document", response=VersionOut)
def publish_document(request: HttpRequest, slug: str, payload: DocumentIn) -> VersionOut:
    data = payload.model_dump()
    data["comment"] = data["comment"].strip() or "Edición desde el panel"
    return VersionOut(version=store.publish(slug, actor=request.user.username, **data))


@router.post("/tenants/{slug}/rollback", response=VersionOut)
def rollback_document(request: HttpRequest, slug: str, payload: RollbackIn) -> VersionOut:
    return VersionOut(
        version=store.rollback(slug, actor=request.user.username, **payload.model_dump())
    )


@router.post("/tenants/{slug}/status", response=VersionOut)
def change_status(request: HttpRequest, slug: str, payload: StatusIn) -> VersionOut:
    if payload.action not in ("activate", "pause", "resume"):
        raise store.StoreError("bad_request", "Acción de estado no válida")
    return VersionOut(
        version=store.change_status(
            slug,
            action=cast(Literal["activate", "pause", "resume"], payload.action),
            actor=request.user.username,
            confirm_slug=payload.confirm_slug,
        )
    )


@router.put("/tenants/{slug}/secrets", response={204: None})
def set_secrets(request: HttpRequest, slug: str, payload: SecretsIn) -> tuple[int, None]:
    store.set_secrets(slug, secrets=payload.secrets, actor=request.user.username)
    return 204, None


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


@router.post("/tenants/{slug}/telegram-webhook", response=service.WebhookRegisterOut)
def telegram_set_webhook(request: HttpRequest, slug: str) -> service.WebhookRegisterOut:
    return service.telegram_set_webhook(slug, actor=request.user.username)


@router.post("/tenants/{slug}/owner-invite", response=service.OwnerInviteOut)
def tenant_owner_invite(request: HttpRequest, slug: str) -> service.OwnerInviteOut:
    return service.tenant_owner_invite(slug, actor=request.user.username)


@router.post("/tenants/{slug}/delete", response=service.DeleteTenantOut)
def delete_tenant(
    request: HttpRequest, slug: str, payload: DeleteTenantIn
) -> service.DeleteTenantOut:
    return service.delete_tenant(slug, payload.confirm_slug, actor=request.user.username)
