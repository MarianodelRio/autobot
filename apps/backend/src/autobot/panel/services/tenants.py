"""A tenant's own data: ficha, history, datasets, secrets status, activation,
summary, notifications and on-demand health (ADR-009).

Every read here is scoped to one tenant; `tenant_tx` is used where the query reuses
platform code that already opens one (`activation.checklist`, `runtime.summary.
build_summary`). Everywhere else, cross-tenant tables (`tenant_document_version`,
`tenant_dataset_version`, `tenant_secret`) are read `.using("owner")`, same as
`tenancy.store` (CLAUDE.md, ADR-009): they carry no `tenant_id` RLS of their own.
"""

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from django.conf import settings
from django.db import connections, transaction
from django.utils import timezone
from ninja import Schema

from autobot.channels.telegram.polling import Source
from autobot.channels.telegram.registration import (
    WebhookError,
    is_webhook_registered,
    remove_bot_webhook,
    resolve_tenant_bot,
)
from autobot.ops import health, tenant_actions
from autobot.ops.audit import record_tenant
from autobot.ops.models import OpsAlert
from autobot.ops.status import tenant_status
from autobot.owner import links as owner_links
from autobot.panel.errors import ApiError
from autobot.panel.services._common import get_tenant_or_404
from autobot.panel.services.month import month_aggregates
from autobot.runtime import privacy
from autobot.runtime.models import Notification
from autobot.runtime.summary import build_summary, month_to_date
from autobot.tenancy import activation, dataset_library, store
from autobot.tenancy.crypto import SecretsUnreadable, decrypt
from autobot.tenancy.links import channel_link
from autobot.tenancy.models import Tenant, TenantDatasetVersion, TenantDocumentVersion, TenantSecret
from autobot.tenancy.registry import LoadedTenant
from autobot.tenancy.schema import SECRETS_SCHEMA


def resolve_dataset_choices(
    pack: str, choices: dict[str, str] | None
) -> tuple[dict[str, dict[str, str]] | None, dict[str, tuple[str, int, str]] | None]:
    """A new tenant's `dataset_choices` ({dataset name -> library entry name},
    always its latest version) resolved to the files `store.create_tenant` needs and
    the origin it records on the resulting `TenantDatasetVersion`."""
    if not choices:
        return None, None
    datasets: dict[str, dict[str, str]] = {}
    origins: dict[str, tuple[str, int, str]] = {}
    for dataset_name, entry_name in choices.items():
        try:
            entry = dataset_library.get(pack, dataset_name, entry_name)
        except dataset_library.LibraryError as error:
            raise store.StoreError(
                "bad_request", error.message, [f"datasets.{dataset_name}: {error.message}"]
            ) from None
        datasets[dataset_name] = entry.files
        origins[dataset_name] = dataset_library.origin(entry)
    return datasets, origins


def tenant_apply_dataset(
    slug: str, dataset: str, *, name: str, version: int | None, comment: str, actor: str
) -> int:
    """Copies a library entry into an existing tenant's dataset (the "Aplicar" button),
    returning its resulting version — the dataset's current one when the content was
    already identical, since `import_dataset` then creates nothing."""
    tenant = get_tenant_or_404(slug)
    try:
        result = dataset_library.apply_to_tenant(
            slug,
            dataset,
            pack=tenant.document.pack,
            name=name,
            version=version,
            actor=actor,
            comment=comment,
        )
    except dataset_library.LibraryError as error:
        raise ApiError("bad_request", error.message, 400) from None
    if result is not None:
        return result
    current = (
        TenantDatasetVersion.objects.using("owner")
        .filter(tenant_id=tenant.id, name=dataset)
        .order_by("-version")
        .first()
    )
    return current.version if current else 0


class DatasetStatusOut(Schema):
    version: int | None
    author: str | None
    comment: str
    created_at: datetime | None
    source_name: str | None
    source_version: int | None
    newer_version_available: int | None  # the library's version, if newer than ours


def tenant_dataset_status(slug: str, dataset: str) -> DatasetStatusOut:
    """The ficha's "Horarios en uso": never the dataset's own content."""
    tenant = get_tenant_or_404(slug)
    current = (
        TenantDatasetVersion.objects.using("owner")
        .filter(tenant_id=tenant.id, name=dataset)
        .order_by("-version")
        .first()
    )
    newer = None
    if current is not None and current.source_name:
        latest = dataset_library.latest(tenant.document.pack, dataset, current.source_name)
        if latest is not None and latest.version > (current.source_version or 0):
            newer = latest.version
    if current is None:
        return DatasetStatusOut(
            version=None,
            author=None,
            comment="",
            created_at=None,
            source_name=None,
            source_version=None,
            newer_version_available=None,
        )
    return DatasetStatusOut(
        version=current.version,
        author=current.author,
        comment=current.comment,
        created_at=current.created_at,
        source_name=current.source_name,
        source_version=current.source_version,
        newer_version_available=newer,
    )


def _health_checked_at(tenant_id: UUID) -> datetime | None:
    snapshot = health.read_snapshot(tenant_id)
    return snapshot.checked_at if snapshot is not None else None


class MonthKpis(Schema):
    inbound: int
    outbound: int
    users: int
    cost_eur: Decimal


def _month_kpis(tenant: LoadedTenant, now: datetime) -> MonthKpis:
    start, _ = month_to_date(now, tenant.info.timezone)
    figures = month_aggregates([tenant.id], start)[tenant.id]
    return MonthKpis(
        inbound=figures.inbound,
        outbound=figures.outbound,
        users=figures.users,
        cost_eur=figures.cost_eur,
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
    owner_invite_pending: bool
    month: MonthKpis


def tenant_detail(slug: str, *, now: datetime | None = None) -> TenantDetail:
    now = now or timezone.now()
    tenant = get_tenant_or_404(slug)
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
        owner_invite_pending=owner_links.invite_pending(tenant.id),
        month=_month_kpis(tenant, now),
    )


class VersionSummary(Schema):
    version: int
    author: str
    comment: str
    created_at: datetime


def tenant_versions(
    slug: str, *, limit: int = 50, before: int | None = None
) -> list[VersionSummary]:
    """Newest first, `limit` at a time; `before` is the oldest version already shown."""
    tenant = get_tenant_or_404(slug)
    queryset = TenantDocumentVersion.objects.using("owner").filter(tenant_id=tenant.id)
    if before is not None:
        queryset = queryset.filter(version__lt=before)
    rows = queryset.order_by("-version").values("version", "author", "comment", "created_at")[
        :limit
    ]
    return [VersionSummary(**row) for row in rows]


class VersionDetail(VersionSummary):
    document: dict[str, Any]


def tenant_version(slug: str, version: int) -> VersionDetail:
    tenant = get_tenant_or_404(slug)
    row = (
        TenantDocumentVersion.objects.using("owner")
        .filter(tenant_id=tenant.id, version=version)
        .values("version", "author", "comment", "created_at", "document")
        .first()
    )
    if row is None:
        raise ApiError("not_found", "No se encuentra esa versión", 404)
    return VersionDetail(**row)


SECRET_FIELDS: dict[str, tuple[str, str, bool]] = {
    # name -> (label, help, generatable)
    "app_secret": ("Secreto de la app", "App de Meta, Ajustes básicos", False),
    "access_token": ("Token de acceso", "Token permanente del System User", False),
    "verify_token": (
        "Token de verificación",
        "Se pega también en el webhook de Meta",
        True,
    ),
    "bot_token": ("Token del bot", "Lo da @BotFather", False),
    "webhook_secret": ("Secreto del webhook", "Mínimo 32 caracteres", True),
}


class SecretField(Schema):
    name: str
    set: bool
    label: str
    help: str
    generatable: bool


class SecretsStatus(Schema):
    channel_type: Literal["whatsapp", "telegram"]
    readable: bool
    updated_at: datetime | None
    updated_by: str | None
    fields: list[SecretField]


def tenant_secrets(slug: str) -> SecretsStatus:
    tenant = get_tenant_or_404(slug)
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
        fields=[
            SecretField(
                name=name,
                set=name in present,
                label=SECRET_FIELDS[name][0],
                help=SECRET_FIELDS[name][1],
                generatable=SECRET_FIELDS[name][2],
            )
            for name in schema.model_fields
        ],
    )


class SecretsUpdateOut(Schema):
    telegram_webhook_registered: bool | None


def update_secrets(slug: str, *, secrets: dict[str, str], actor: str) -> SecretsUpdateOut:
    """Writes the secrets (`tenancy.store`, its own transaction) and, for Telegram,
    re-registers the webhook right after: a changed `bot_token` or
    `webhook_secret` otherwise leaves the old one in place and the panel still
    says "Registrado". Never inside `store.set_secrets`'s own transaction (no open
    transaction during a call to Telegram, CLAUDE.md)."""
    store.set_secrets(slug, secrets=secrets, actor=actor)
    tenant = get_tenant_or_404(slug)
    if tenant.document.channel is None or tenant.document.channel.type != "telegram":
        return SecretsUpdateOut(telegram_webhook_registered=None)
    try:
        tenant_actions.set_telegram_webhook(
            slug,
            actor=actor,
            tenant=tenant,
            tenant_only=True,
            summary="Webhook de Telegram registrado tras cambiar credenciales",
        )
    except tenant_actions.ActionError:
        return SecretsUpdateOut(telegram_webhook_registered=False)
    return SecretsUpdateOut(telegram_webhook_registered=True)


class ChecklistItemOut(Schema):
    key: str
    label: str
    ok: bool
    blocking: bool
    detail: str


def tenant_checklist(slug: str) -> list[ChecklistItemOut]:
    get_tenant_or_404(slug)  # 404 before running the checklist
    return [
        ChecklistItemOut(key=i.key, label=i.label, ok=i.ok, blocking=i.blocking, detail=i.detail)
        for i in activation.checklist(slug, refresh=False).items
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
    tenant = get_tenant_or_404(slug)
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
    tenant = get_tenant_or_404(slug)
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
    tenant = get_tenant_or_404(slug)
    issues = health.daily(tenant.id, lambda: health.tenant_health(tenant), force=True)
    return [HealthIssueOut(code=i.code, message=i.message, severity=i.severity) for i in issues]


class WebhookRegisterOut(Schema):
    url: str


def telegram_set_webhook(slug: str, actor: str) -> WebhookRegisterOut:
    tenant = get_tenant_or_404(slug)
    channel = tenant.document.channel
    if channel is None or channel.type != "telegram":
        raise ApiError("bad_request", "El canal no es Telegram", 400)
    try:
        url = tenant_actions.set_telegram_webhook(
            slug, actor=actor, tenant=tenant, tenant_only=True
        )
    except tenant_actions.ActionError:
        raise ApiError("unavailable", "No se pudo registrar el webhook.", 502) from None
    return WebhookRegisterOut(url=url)


class WebhookStatusOut(Schema):
    registered: bool | None


def telegram_webhook_status(slug: str) -> WebhookStatusOut:
    """Asks Telegram (outside any transaction) whether the webhook is set to the expected
    url. `registered` is None when it cannot be known."""
    tenant = get_tenant_or_404(slug)
    channel = tenant.document.channel
    if channel is None or channel.type != "telegram":
        raise ApiError("bad_request", "El canal no es Telegram", 400)
    return WebhookStatusOut(registered=is_webhook_registered(slug))


class OwnerInviteOut(Schema):
    url: str
    expires_at: datetime
    replaces_chat: bool


def tenant_owner_invite(slug: str, actor: str) -> OwnerInviteOut:
    tenant = get_tenant_or_404(slug)
    try:
        link = tenant_actions.create_owner_invite(tenant, actor=actor)
    except tenant_actions.ActionError as e:
        raise ApiError("bad_request", str(e), 400) from None
    return OwnerInviteOut(
        url=link.url, expires_at=link.expires_at, replaces_chat=link.replaces_chat
    )


# The whole export is built in memory and sent as one JSON response: past this many
# rows it is the `tenant_data_export` command's job (it writes a private file).
MAX_EXPORT_ROWS = 50_000


class ExportOut(Schema):
    tenant: str
    data: dict[str, Any]


def _count_rows(tenant_id: UUID) -> int:
    """How many rows `privacy.export_data` would read: one query, whatever the number of
    tables."""
    connection = connections["owner"]
    quote = connection.ops.quote_name
    selects = [
        f"SELECT count(*) AS n FROM {quote(model._meta.db_table)} WHERE tenant_id = %s"
        for model in privacy.MODELS
    ]
    with connection.cursor() as cursor:
        cursor.execute(
            f"SELECT sum(n) FROM ({' UNION ALL '.join(selects)}) AS counts",
            [tenant_id] * len(selects),
        )
        (total,) = cursor.fetchone()
    return int(total or 0)


def tenant_export(slug: str, *, actor: str) -> ExportOut:
    """The panel equivalent of `tenant_data_export`, downloaded as JSON instead of
    written to an operator-chosen local path."""
    tenant = get_tenant_or_404(slug)
    db_tenant = Tenant.objects.using("owner").get(pk=tenant.id)
    with transaction.atomic(using="owner"):
        if _count_rows(tenant.id) > MAX_EXPORT_ROWS:
            raise ApiError(
                "too_large",
                f"Hay más de {MAX_EXPORT_ROWS} filas: usa el comando tenant_data_export.",
                413,
            )
        data = privacy.export_data(db_tenant)
    # Audited before the data leaves: if the audit fails, nothing is returned.
    record_tenant(actor, "tenant.export", tenant, "Exportación de datos del negocio")
    return ExportOut(**data)


class OwnerUnlinkOut(Schema):
    had_chat: bool


def tenant_owner_unlink(slug: str, actor: str) -> OwnerUnlinkOut:
    """Disconnect the owner's chat and clear any pending invite, the panel equivalent
    of the `owner_unlink` command."""
    tenant = get_tenant_or_404(slug)
    return OwnerUnlinkOut(had_chat=tenant_actions.unlink_owner(tenant, actor=actor))


class DeleteTenantOut(Schema):
    telegram_webhook_removed: bool | None


def _resolve_bot_before_purge(tenant: LoadedTenant) -> tuple[Source | None, bool]:
    """The tenant's Telegram bot, resolved BEFORE the purge (afterwards its secrets are
    gone). Returns `(bot, unresolved)`: `unresolved` when it has a bot but it cannot be
    read, so its webhook will have to be removed by hand."""
    channel = tenant.document.channel
    if (
        channel is None
        or channel.type != "telegram"
        or not TenantSecret.objects.using("owner").filter(tenant_id=tenant.id).exists()
    ):
        return None, False
    try:
        return resolve_tenant_bot(tenant.slug), False
    except WebhookError, SecretsUnreadable:
        return None, True


def _remove_webhook_after(bot: Source | None, *, unresolved: bool) -> bool | None:
    """Removes the deleted tenant's webhook once the deletion is committed (never inside
    its transaction: it reaches Telegram). None when it had no bot to remove."""
    if bot is None:
        return False if unresolved else None
    try:
        remove_bot_webhook(bot)
    except WebhookError:
        return False
    return True


def delete_tenant(slug: str, confirm_slug: str, actor: str) -> DeleteTenantOut:
    tenant = get_tenant_or_404(slug)
    if confirm_slug != slug:
        raise ApiError("bad_request", "El slug no coincide.", 400)
    if tenant.document.demo is not None:
        raise ApiError("bad_request", "Los demos no se pueden eliminar.", 400)
    if tenant.document.status == "active":
        raise ApiError("conflict", "Páusalo antes de eliminarlo.", 409)

    bot, bot_unresolved = _resolve_bot_before_purge(tenant)
    db_tenant = Tenant.objects.using("owner").get(pk=tenant.id)
    try:
        with transaction.atomic(using="owner"):
            if tenant.document.status != "offboarded":
                store.change_status(slug, action="offboard", actor=actor, confirm_slug=slug)
            privacy.purge(db_tenant, actor=actor)
    except privacy.PurgeBlocked:
        raise ApiError(
            "conflict", "Hay trabajos en curso; inténtalo en unos segundos.", 409
        ) from None
    return DeleteTenantOut(
        telegram_webhook_removed=_remove_webhook_after(bot, unresolved=bot_unresolved)
    )
