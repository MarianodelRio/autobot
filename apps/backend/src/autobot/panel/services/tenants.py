"""A tenant's own data: ficha, history, datasets, secrets status, activation,
summary, notifications and on-demand health (ADR-009).

Every read here is scoped to one tenant; `tenant_tx` is used where the query reuses
platform code that already opens one (`activation.checklist`, `runtime.summary.
build_summary`). Everywhere else, cross-tenant tables (`tenant_document_version`,
`tenant_dataset_version`, `tenant_secret`) are read `.using("owner")`, same as
`tenancy.store` (CLAUDE.md, ADR-009): they carry no `tenant_id` RLS of their own.
"""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone
from ninja import Schema

from autobot.ops import health
from autobot.ops.models import OpsAlert
from autobot.ops.status import tenant_status
from autobot.owner import links as owner_links
from autobot.panel.errors import ApiError
from autobot.runtime import costs
from autobot.runtime.models import InboundEvent, Notification, OutboundMessage
from autobot.runtime.summary import build_summary, month_to_date
from autobot.tenancy.crypto import SecretsUnreadable, decrypt
from autobot.tenancy.links import channel_link
from autobot.tenancy.models import TenantDatasetVersion, TenantDocumentVersion, TenantSecret
from autobot.tenancy.registry import LoadedTenant, get_registry
from autobot.tenancy.schema import SECRETS_SCHEMA


def _tenant(slug: str) -> LoadedTenant:
    tenant = get_registry().by_slug.get(slug)
    if tenant is None:
        raise ApiError("not_found", "No se encuentra el negocio", 404)
    return tenant


def _health_checked_at(tenant_id: UUID) -> datetime | None:
    cached = cache.get(f"health:{tenant_id}")
    if isinstance(cached, dict) and "checked_at" in cached:
        return datetime.fromtimestamp(cached["checked_at"], tz=UTC)
    return None


class MonthKpis(Schema):
    inbound: int
    outbound: int
    users: int
    cost_eur: Decimal


def _month_kpis(tenant: LoadedTenant, now: datetime) -> MonthKpis:
    start, _ = month_to_date(now, tenant.info.timezone)
    outbound_qs = OutboundMessage.objects.using("owner").filter(
        tenant_id=tenant.id, status="sent", sent_at__gte=start
    )
    inbound = (
        InboundEvent.objects.using("owner")
        .filter(tenant_id=tenant.id, kind="message", received_at__gte=start)
        .count()
    )
    cost_eur = costs.cost_of(
        costs.billable_counts(
            OutboundMessage.objects.using("owner").filter(tenant_id=tenant.id, sent_at__gte=start)
        )
    )
    return MonthKpis(
        inbound=inbound,
        outbound=outbound_qs.count(),
        users=outbound_qs.values("contact_id").distinct().count(),
        cost_eur=cost_eur,
    )


class OpenAlert(Schema):
    id: UUID
    text: str
    severity: str


class TenantDetail(Schema):
    slug: str
    name: str
    pack: str
    status: str
    timezone: str
    document: dict[str, Any]
    version: int | None
    degraded: list[str]
    ambiguous: bool
    main_disabled: list[str]
    health: str
    health_reasons: list[str]
    open_alerts: list[OpenAlert]
    health_checked_at: datetime | None
    channel_type: Literal["whatsapp", "telegram"] | None
    webhook_url: str | None
    public_link: str | None
    owner_linked: bool
    month: MonthKpis


def tenant_detail(slug: str, *, now: datetime | None = None) -> TenantDetail:
    now = now or timezone.now()
    tenant = _tenant(slug)
    channel = tenant.document.channel
    webhook_url = None
    public_link = None
    if channel is not None:
        webhook_url = f"{settings.PUBLIC_URL}/webhooks/{channel.type}/{channel.public_id}"
        try:
            public_link = channel_link(channel)
        except ValueError:
            public_link = None
    status = tenant_status(tenant)
    return TenantDetail(
        slug=tenant.slug,
        name=tenant.document.name,
        pack=tenant.document.pack,
        status=tenant.document.status,
        timezone=tenant.document.timezone,
        document=tenant.document.model_dump(mode="json"),
        version=tenant.version,
        degraded=tenant.degraded,
        ambiguous=tenant.ambiguous,
        main_disabled=tenant.main_disabled,
        health=status.level,
        health_reasons=status.reasons,
        open_alerts=[
            OpenAlert(id=alert.id, text=alert.text, severity=alert.severity)
            for alert in OpsAlert.objects.using("owner")
            .filter(tenant_id=tenant.id, resolved_at__isnull=True)
            .order_by("-last_seen_at")
        ],
        health_checked_at=_health_checked_at(tenant.id),
        channel_type=channel.type if channel is not None else None,
        webhook_url=webhook_url,
        public_link=public_link,
        owner_linked=owner_links.owner_chat(tenant.id) is not None,
        month=_month_kpis(tenant, now),
    )


class VersionSummary(Schema):
    version: int
    author: str
    comment: str
    created_at: datetime


def tenant_versions(slug: str) -> list[VersionSummary]:
    tenant = _tenant(slug)
    rows = (
        TenantDocumentVersion.objects.using("owner")
        .filter(tenant_id=tenant.id)
        .order_by("-version")
        .values("version", "author", "comment", "created_at")
    )
    return [VersionSummary(**row) for row in rows]


class VersionDetail(VersionSummary):
    document: dict[str, Any]


def tenant_version(slug: str, version: int) -> VersionDetail:
    tenant = _tenant(slug)
    row = (
        TenantDocumentVersion.objects.using("owner")
        .filter(tenant_id=tenant.id, version=version)
        .values("version", "author", "comment", "created_at", "document")
        .first()
    )
    if row is None:
        raise ApiError("not_found", "No se encuentra esa versión", 404)
    return VersionDetail(**row)


class DatasetVersionOut(Schema):
    name: str
    version: int
    sha256: str
    author: str
    comment: str
    created_at: datetime


def tenant_datasets(slug: str) -> list[DatasetVersionOut]:
    tenant = _tenant(slug)
    rows = (
        TenantDatasetVersion.objects.using("owner")
        .filter(tenant_id=tenant.id)
        .order_by("name", "-version")
        .distinct("name")
        .values("name", "version", "sha256", "author", "comment", "created_at")
    )
    return [DatasetVersionOut(**row) for row in rows]


class SecretField(Schema):
    name: str
    set: bool


class SecretsStatus(Schema):
    channel_type: Literal["whatsapp", "telegram"]
    readable: bool
    updated_at: datetime | None
    updated_by: str | None
    fields: list[SecretField]


def tenant_secrets(slug: str) -> SecretsStatus:
    tenant = _tenant(slug)
    if tenant.document.channel is None:
        raise ApiError("bad_request", "Un demo no admite secretos de canal", 400)
    channel_type = tenant.document.channel.type
    schema = SECRETS_SCHEMA[channel_type]
    row = TenantSecret.objects.using("owner").filter(tenant_id=tenant.id).first()
    readable = False
    present: set[str] = set()
    if row is not None:
        try:
            decrypted = decrypt(bytes(row.ciphertext))
            present = {name for name, value in decrypted.items() if value}
            readable = True
        except SecretsUnreadable:
            readable = False
    return SecretsStatus(
        channel_type=channel_type,
        readable=readable,
        updated_at=row.updated_at if row is not None else None,
        updated_by=row.updated_by if row is not None else None,
        fields=[SecretField(name=name, set=name in present) for name in schema.model_fields],
    )


class ChecklistItemOut(Schema):
    key: str
    label: str
    ok: bool
    blocking: bool
    detail: str


def tenant_checklist(slug: str) -> list[ChecklistItemOut]:
    from autobot.tenancy import activation

    _tenant(slug)  # 404 before running the checklist
    return [
        ChecklistItemOut(key=i.key, label=i.label, ok=i.ok, blocking=i.blocking, detail=i.detail)
        for i in activation.checklist(slug).items
    ]


class SummaryLineOut(Schema):
    icon: str
    label: str
    value: Decimal
    unit: Literal["count", "eur"]
    note: str | None


class SummaryOut(Schema):
    start: datetime
    end: datetime
    pack_lines: list[SummaryLineOut]
    pack_failed: bool
    users: int
    messages: int
    cost_eur: Decimal


def tenant_summary(slug: str, *, now: datetime | None = None) -> SummaryOut:
    tenant = _tenant(slug)
    now = now or timezone.now()
    start, end = month_to_date(now, tenant.info.timezone)
    block = build_summary(tenant, start, end)
    return SummaryOut(
        start=block.start,
        end=block.end,
        pack_lines=[
            SummaryLineOut(
                icon=line.icon, label=line.label, value=line.value, unit=line.unit, note=line.note
            )
            for line in block.pack_lines
        ],
        pack_failed=block.pack_failed,
        users=block.generic.users,
        messages=block.generic.messages,
        cost_eur=block.cost,
    )


class NotificationOut(Schema):
    kind: str
    text: str
    status: str
    created_at: datetime
    sent_at: datetime | None


MAX_NOTIFICATIONS = 50


def tenant_notifications(slug: str) -> list[NotificationOut]:
    tenant = _tenant(slug)
    rows = (
        Notification.objects.using("owner")
        .filter(tenant_id=tenant.id, audience=Notification.Audience.OWNER)
        .order_by("-created_at")[:MAX_NOTIFICATIONS]
    )
    return [
        NotificationOut(
            kind=n.kind, text=n.text, status=n.status, created_at=n.created_at, sent_at=n.sent_at
        )
        for n in rows
    ]


class HealthIssueOut(Schema):
    code: str
    message: str
    severity: str


def tenant_health_check(slug: str) -> list[HealthIssueOut]:
    tenant = _tenant(slug)
    issues = health.daily(tenant.id, lambda: health.tenant_health(tenant), force=True)
    return [HealthIssueOut(code=i.code, message=i.message, severity=i.severity) for i in issues]
