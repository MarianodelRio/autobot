"""Shared health classification for tenant lists, details and activation."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import timedelta
from typing import Literal, Protocol
from uuid import UUID

from django.utils import timezone

from autobot.ops.health import HealthSnapshot, read_snapshot
from autobot.tenancy.registry import LoadedTenant


class IncidentLike(Protocol):
    """An open incident (`ops.incidents.Incident`)."""

    @property
    def severity(self) -> str: ...

    @property
    def tenant_id(self) -> UUID | None: ...

    @property
    def title(self) -> str: ...


type Level = Literal["ok", "notice", "warning", "critical", "unknown"]


@dataclass(frozen=True)
class TenantStatus:
    level: Level
    reasons: list[str]


def tenant_status(
    tenant: LoadedTenant,
    *,
    incidents: Sequence[IncidentLike] = (),
    snapshots: Mapping[UUID | str, HealthSnapshot | None] | None = None,
) -> TenantStatus:
    """`incidents`: the open incidents (`ops.incidents.open_incidents`); those of this
    tenant raise its level by their severity (a 🟡 one only to `notice`), with their title
    as the reason. `snapshots`: health snapshots already read in bulk (lists), to avoid
    one cache query per tenant."""
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
    for incident in incidents:
        if incident.tenant_id == tenant.id:
            target = {"critical": critical, "warning": warning, "notice": notice}.get(
                incident.severity
            )
            if target is not None:
                target.append(incident.title)
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
