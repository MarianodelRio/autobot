"""Activation checks run provider health before any configuration write transaction."""

from dataclasses import dataclass

from autobot.ops import health
from autobot.ops.status import tenant_status
from autobot.runtime.models import InboundEvent, OwnerLink
from autobot.tenancy import store
from autobot.tenancy.registry import load_registry
from autobot.tenancy.schema import WhatsAppChannel
from autobot.tenancy.tx import tenant_tx


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


def checklist(slug: str) -> Checklist:
    from packs.registry import PACKS

    sources = store.current_sources()
    store._current(slug, sources)
    registry = load_registry(sources, PACKS)
    tenant = registry.by_slug.get(slug)
    valid = tenant is not None and not tenant.is_degraded and not tenant.ambiguous
    channel_ok = secrets_ok = healthy = templates_ok = inbound = owner = False
    if tenant is not None:
        channel = tenant.document.channel
        channel_ok = channel is not None and channel.complete
        secrets_ok = tenant.secrets is not None and not any(
            "decrypt" in issue for issue in tenant.main_disabled
        )
        issues = health.daily(tenant.id, lambda: health.tenant_health(tenant), force=True)
        healthy = tenant_status(tenant).level != "critical"
        templates_ok = not isinstance(channel, WhatsAppChannel) or not any(
            issue.code == "templates" for issue in issues
        )
        with tenant_tx(tenant.id):
            inbound = InboundEvent.objects.filter(
                tenant_id=tenant.id, channel="main", kind="message"
            ).exists()
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
            Item(key, label, ok, blocking, "Comprobado" if ok else "Pendiente")
            for key, label, ok, blocking in rows
        ]
    )
