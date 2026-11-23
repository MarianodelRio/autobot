"""Shared health classification for tenant lists, details and activation."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import timedelta
from typing import Literal, Protocol
from uuid import UUID

from django.utils import timezone

from autobot.ops.health import HealthSnapshot, read_snapshot
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
    tenant: LoadedTenant,
    *,
    open_alerts: Sequence[OpsAlertLike] = (),
    snapshots: Mapping[UUID | str, HealthSnapshot | None] | None = None,
) -> TenantStatus:
    """`snapshots`: health snapshots already read in bulk (lists), to avoid one cache
    query per tenant."""
    critical: list[str] = []
    warning: list[str] = []
    notice: list[str] = []
    if tenant.is_degraded:
        critical.append("Configuración degradada")
    if tenant.document.status == "active" and not tenant.is_demo and not tenant.main_enabled:
        critical.append("Canal principal desactivado")
    snapshot = snapshots[tenant.id] if snapshots is not None else read_snapshot(tenant.id)
    if snapshot is not None:
        for issue in snapshot.issues:
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
    if snapshot is None or timezone.now() - snapshot.checked_at > timedelta(hours=24):
        return TenantStatus("unknown", ["La comprobación de salud falta o tiene más de 24 horas"])
    return TenantStatus("ok", [])
