"""Shared health classification for tenant lists, details and activation."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, Protocol
from uuid import UUID

from django.core.cache import cache
from django.utils import timezone

from autobot.tenancy.registry import LoadedTenant


class OpsAlertLike(Protocol):
    @property
    def severity(self) -> str: ...

    @property
    def tenant_id(self) -> UUID | None: ...


type Level = Literal["ok", "notice", "warning", "critical", "unknown"]


@dataclass(frozen=True)
class TenantStatus:
    level: Level
    reasons: list[str]


def tenant_status(
    tenant: LoadedTenant, *, open_alerts: Sequence[OpsAlertLike] = ()
) -> TenantStatus:
    critical: list[str] = []
    warning: list[str] = []
    notice: list[str] = []
    if tenant.is_degraded:
        critical.append("Configuración degradada")
    if tenant.document.status == "active" and not tenant.is_demo and not tenant.main_enabled:
        critical.append("Canal principal desactivado")
    health = cache.get(f"health:{tenant.id}")
    if isinstance(health, dict):
        for issue in health.get("issues", []):
            target = {"🔴": critical, "🟠": warning, "🟡": notice}.get(issue.severity)
            if target is not None:
                target.append(issue.message)
    for alert in open_alerts:
        if alert.tenant_id == tenant.id:
            if alert.severity == "critical":
                critical.append("Alerta crítica abierta")
            elif alert.severity == "warning":
                warning.append("Alerta de aviso abierta")
            elif alert.severity == "notice":
                notice.append("Alerta de atención abierta")
    ranked: list[tuple[Level, list[str]]] = [
        ("critical", critical),
        ("warning", warning),
        ("notice", notice),
    ]
    for level, reasons in ranked:
        if reasons:
            return TenantStatus(level, list(dict.fromkeys(reasons)))
    if (
        not isinstance(health, dict)
        or timezone.now().timestamp() - health.get("checked_at", 0) > 86400
    ):
        return TenantStatus("unknown", ["La comprobación de salud falta o tiene más de 24 horas"])
    return TenantStatus("ok", [])
