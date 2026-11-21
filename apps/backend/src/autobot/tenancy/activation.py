"""Activation checks run provider health before any configuration write transaction."""

from dataclasses import dataclass
from uuid import UUID

from autobot.ops import health
from autobot.ops.status import tenant_status
from autobot.runtime.models import InboundEvent, OwnerLink
from autobot.tenancy import store
from autobot.tenancy.registry import LoadedTenant, load_registry
from autobot.tenancy.schema import Channel, WhatsAppChannel
from autobot.tenancy.tx import tenant_tx
from packs import registry as packs_registry


@dataclass(frozen=True)
class Item:
    key: str
    label: str
    ok: bool
    blocking: bool
    detail: str


@dataclass(frozen=True)
class Checklist:
    items: list[Item]

    @property
    def blocking(self) -> list[str]:
        return [item.key for item in self.items if item.blocking and not item.ok]


def _channel_complete(channel: Channel | None) -> bool:
    # `complete` alone (app_id/waba_id/phone_number_id) still leaves a WhatsApp tenant
    # without `display_phone`, so no public link and no QR (tenancy.links.channel_link):
    # the checklist must not call that "ok".
    return (
        channel is not None
        and channel.complete
        and (not isinstance(channel, WhatsAppChannel) or bool(channel.display_phone))
    )


def _health_issues(tenant: LoadedTenant, refresh: bool) -> tuple[bool, list[health.Issue]]:
    """Whether the health is known, and its issues (the cache holds them when not
    refreshing)."""
    if refresh:
        return True, health.daily(tenant.id, lambda: health.tenant_health(tenant), force=True)
    snapshot = health.read_snapshot(tenant.id)
    return (True, snapshot.issues) if snapshot is not None else (False, [])


def _tester_wrote(tenant_id: UUID) -> bool:
    with tenant_tx(tenant_id):
        # A message from a stranger during onboarding is saved but ignored
        # (runtime.inbound), not answered: it must not count as a tester.
        return (
            InboundEvent.objects.filter(tenant_id=tenant_id, channel="main", kind="message")
            .exclude(status=InboundEvent.Status.IGNORED)
            .exists()
        )


def checklist(slug: str, *, refresh: bool = True) -> Checklist:
    """`refresh=True` (activating, and the panel's «Comprobar») asks the providers now.
    `refresh=False` (the panel's plain reads) only looks at the cached health: a page
    load must not call Meta, Telegram or Google, and an unchecked health counts as
    pending, never as ok."""
    sources = store.current_sources()
    store.find_source(slug, sources)
    tenant = load_registry(sources, packs_registry.PACKS).by_slug.get(slug)
    valid = tenant is not None and not tenant.is_degraded and not tenant.ambiguous
    channel_ok = secrets_ok = healthy = templates_ok = inbound = owner = False
    checked = True
    if tenant is not None:
        channel = tenant.document.channel
        channel_ok = _channel_complete(channel)
        secrets_ok = tenant.secrets is not None and not any(
            "decrypt" in issue for issue in tenant.main_disabled
        )
        checked, issues = _health_issues(tenant, refresh)
        healthy = checked and tenant_status(tenant).level != "critical"
        templates_ok = checked and (
            not isinstance(channel, WhatsAppChannel)
            or not any(issue.code == "templates" for issue in issues)
        )
        inbound = _tester_wrote(tenant.id)
        owner = OwnerLink.objects.filter(tenant_id=tenant.id, chat_id__isnull=False).exists()
    rows = [
        ("document", "Documento válido y sin degradación", valid, True),
        ("channel", "Ids de canal completos", channel_ok, True),
        ("secrets", "Secretos presentes y legibles", secrets_ok, True),
        ("health", "Salud del canal sin problemas críticos", healthy, True),
        ("templates", "Plantillas de WhatsApp aprobadas", templates_ok, True),
        ("tester", "Algún tester ha escrito por el canal principal", inbound, True),
        ("owner", "Dueño enlazado", owner, False),
    ]
    return Checklist(
        [
            Item(
                key,
                label,
                ok,
                blocking,
                "Comprobado"
                if ok
                else "Sin comprobar: pulsa «Comprobar»."
                if not checked and key in ("health", "templates")
                else "Pendiente",
            )
            for key, label, ok, blocking in rows
        ]
    )
