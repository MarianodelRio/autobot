"""The operator's texts (ADR-029), from the plain data of `ops.report`: pure functions,
no database, so the wording can change without touching how the figures are read.
`*bold*` is Telegram's own markup (the adapter turns it into `<b>`); times are Madrid's.

Lists that grow with the platform (incidents, tenants) are capped, so a text never
outgrows the common limit (`MAX_TEXT`): the rest is in the panel."""

from collections.abc import Sequence
from datetime import datetime, timedelta

from autobot.ops.report import (
    MADRID,
    Backups,
    Cleanup,
    Day,
    Figures,
    IncidentLine,
    PlatformStatus,
    Resources,
    Services,
    TenantLine,
)

MAX_ITEMS = 15  # incidents or tenants listed one by one; past it, a count
LEVEL_ICON = {"ok": "🟢", "notice": "🟡", "warning": "🟠", "critical": "🔴"}
SEVERITY_ICON = {"critical": "🔴", "warning": "🟠", "notice": "🟡", "info": "🟢"}
STATUS_LABEL = {"active": "activo", "onboarding": "en alta", "paused": "en pausa"}
WEEKDAYS = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")


# ── Formatting ──────────────────────────────────────────────────────────────


def number(value: int) -> str:
    """1240 → «1.240», Spanish style."""
    return f"{value:,}".replace(",", ".")


def percent(value: float | None) -> str:
    return "?" if value is None else f"{value:.0f} %"


def size(value: int) -> str:
    gib = value / 1024**3
    if gib >= 1:
        return f"{gib:.1f} GB".replace(".", ",")
    return f"{value / 1024**2:.0f} MB"


def ago(at: datetime, now: datetime) -> str:
    seconds = max(0, int((now - at).total_seconds()))
    if seconds < 60:
        return "hace un momento"
    if seconds < 3600:
        return f"hace {seconds // 60} min"
    if seconds < 2 * 86400:
        return f"hace {seconds // 3600} h"
    return f"hace {seconds // 86400} días"


def clock(at: datetime, now: datetime) -> str:
    """«hoy a las 03:00», «ayer a las 03:00» or «el 21/11 a las 03:00»."""
    local, today = at.astimezone(MADRID), now.astimezone(MADRID).date()
    time = local.strftime("%H:%M")
    if local.date() == today:
        return f"hoy a las {time}"
    if local.date() == today - timedelta(days=1):
        return f"ayer a las {time}"
    return f"el {local.strftime('%d/%m')} a las {time}"


def weekday_date(at: datetime) -> str:
    """«domingo 23/11»."""
    local = at.astimezone(MADRID)
    return f"{WEEKDAYS[local.weekday()]} {local.strftime('%d/%m')}"


def _capped(lines: list[str], hidden: int, what: str) -> list[str]:
    return [*lines, f"… y {hidden} {what} más en el panel."] if hidden else lines


# ── 🩺 Estado ────────────────────────────────────────────────────────────────


def status_text(status: PlatformStatus, now: datetime) -> str:
    lines = [_status_title(status), ""]
    lines.append(_services_line(status.services))
    lines.append(_resources_line(status.resources))
    lines.append(_backup_line(status.backups, now))
    lines.append(_cleanup_line(status.cleanup, now))
    lines.append(_incidents_line(status.incidents))
    if status.troubled:
        names = ", ".join(status.troubled[:MAX_ITEMS])
        lines.append(f"Clientes con problemas: {len(status.troubled)} ({names})")
    return "\n".join(lines)


def _status_title(status: PlatformStatus) -> str:
    if status.level == "critical":
        return "🔴 *Hay problemas*"
    if status.level == "warning":
        return "🟠 *Hay avisos*"
    return "✅ *Todo en orden*"


def _services_line(services: Services | None) -> str:
    if services is None:
        return "Servicios: sin datos (en local no hay; en el servidor, revisa el timer)"
    text = f"Servicios: {services.running}/{services.total} en marcha"
    if services.failing:
        text += f" ⚠️ {', '.join(services.failing)}"
    if services.stale:
        text += " (datos desactualizados)"
    return text


def _resources_line(resources: Resources | None) -> str:
    if resources is None:
        return "Recursos: sin muestra reciente"
    return (
        f"Disco {percent(resources.disk_pct)} · Memoria {percent(resources.mem_pct)}"
        f" · BD {size(resources.db_bytes)}"
    )


def _backup_line(backups: Backups, now: datetime) -> str:
    if backups.finished_at is None and backups.ok is None:
        return "Último backup: sin datos"
    when = ago(backups.finished_at, now) if backups.finished_at else "sin fecha"
    if backups.ok is False:
        return f"Último backup: ❌ falló, {when}"
    return f"Último backup: {when} {'⚠️ atrasado' if backups.stale else '✅'}"


def _cleanup_line(cleanup: Cleanup, now: datetime) -> str:
    if not cleanup.enabled:
        return "Limpieza nocturna: desactivada"
    if cleanup.last_at is None:
        return "Limpieza nocturna: sin pasadas todavía"
    when = clock(cleanup.last_at, now)
    if cleanup.stale:
        failed = "" if cleanup.ok else " (la última falló)"
        return f"Limpieza nocturna: ⚠️ sin pasar desde {when}{failed}"
    if cleanup.ok is None:
        return f"Limpieza nocturna: en curso ({when})"
    return f"Limpieza nocturna: {'✅' if cleanup.ok else '❌ falló'} {when}"


def _incidents_line(incidents: Sequence[IncidentLine]) -> str:
    if not incidents:
        return "Incidencias abiertas: ninguna"
    counts: dict[str, int] = {}
    for incident in incidents:
        counts[incident.severity] = counts.get(incident.severity, 0) + 1
    parts = [f"{counts[s]} {SEVERITY_ICON[s]}" for s in SEVERITY_ICON if s in counts]
    return f"Incidencias abiertas: {len(incidents)} ({', '.join(parts)})"


# ── 🚨 Incidencias ───────────────────────────────────────────────────────────


def incidents_text(incidents: Sequence[IncidentLine], now: datetime) -> str:
    if not incidents:
        return "🚨 *Incidencias abiertas*\n\nNinguna. ✅"
    shown = incidents[:MAX_ITEMS]
    lines = [_incident(incident, now) for incident in shown]
    lines = _capped(lines, len(incidents) - len(shown), "incidencias")
    return f"🚨 *Incidencias abiertas: {len(incidents)}*\n\n" + "\n\n".join(lines)


def _incident(incident: IncidentLine, now: datetime) -> str:
    text = f"{incident.text}\n   desde {ago(incident.since, now)}"
    if incident.new_since_review:
        text += f" · {incident.new_since_review} nuevos desde tu revisión"
    return text


# ── 📊 Hoy ───────────────────────────────────────────────────────────────────


def day_text(day: Day, title: str) -> str:
    total = day.total
    if total.empty:
        return f"{title}\n\nSin mensajes."
    lines = [f"{title}\n", _totals_line(total)]
    detail = [f"{t.name}: {_figures_line(t.figures)}" for t in day.real[:MAX_ITEMS]]
    detail = _capped(detail, len(day.real) - len(detail), "clientes")
    if not day.demos.empty:
        detail.append(f"Demos: {_figures_line(day.demos)}")
    if detail:
        lines += ["", *detail]
    return "\n".join(lines)


def today_title(now: datetime) -> str:
    return f"📊 *Hoy*, hasta las {now.astimezone(MADRID).strftime('%H:%M')}"


def _totals_line(figures: Figures) -> str:
    return (
        f"Recibidos {number(figures.received)} · Enviados {number(figures.sent)}"
        f" · Fallos {number(figures.failed)} · Contactos nuevos {number(figures.new_contacts)}"
    )


def _figures_line(figures: Figures) -> str:
    parts = [f"{number(figures.received)} recibidos", f"{number(figures.sent)} enviados"]
    if figures.failed:
        parts.append(f"⚠️ {number(figures.failed)} fallos")
    return " · ".join(parts)


# ── 🏪 Clientes ──────────────────────────────────────────────────────────────


def tenants_text(lines: Sequence[TenantLine], now: datetime) -> str:
    real = [line for line in lines if not line.demo]
    demos = [line for line in lines if line.demo]
    counts = {status: sum(line.status == status for line in real) for status in STATUS_LABEL}
    head = (
        f"🏪 *Clientes*: {counts['active']} activos · {counts['onboarding']} en alta"
        f" · {counts['paused']} en pausa"
    )
    # Those with a problem first, then by name (the order `lines` already has).
    ordered = sorted(real, key=lambda line: line.level == "ok")
    shown = ordered[:MAX_ITEMS]
    body = _capped([_tenant_line(line, now) for line in shown], len(real) - len(shown), "clientes")
    if not real:
        body = ["Todavía no hay clientes."]
    if demos:
        troubled = sum(line.level != "ok" for line in demos)
        body.append(
            f"Demos: {len(demos)}" + (f", {troubled} con problemas" if troubled else ", todas bien")
        )
    return head + "\n\n" + "\n\n".join(body)


def _tenant_line(line: TenantLine, now: datetime) -> str:
    seen = (
        f"último mensaje {ago(line.last_activity_at, now)}"
        if line.last_activity_at
        else "sin mensajes"
    )
    text = f"{LEVEL_ICON[line.level]} {line.name} · {STATUS_LABEL.get(line.status, line.status)}"
    text += f"\n   {seen}"
    if line.reasons:
        text += f"\n   {line.reasons[0]}"
    return text


# ── 💾 Backups ───────────────────────────────────────────────────────────────


def backups_text(backups: Backups, cleanup: Cleanup, now: datetime) -> str:
    lines = ["💾 *Copias y limpieza*", "", _backup_line(backups, now), _prune_line(backups, now)]
    lines.append(_cleanup_line(cleanup, now))
    return "\n".join(lines)


def _prune_line(backups: Backups, now: datetime) -> str:
    if backups.last_prune_at is None:
        due = " ⚠️ toca make backup-prune" if backups.prune_overdue else ""
        return f"Caducar copias: nunca{due}"
    if backups.prune_overdue:
        return f"Caducar copias: {ago(backups.last_prune_at, now)} ⚠️ toca make backup-prune"
    return f"Caducar copias: {ago(backups.last_prune_at, now)} ✅"


# ── Resumen diario ───────────────────────────────────────────────────────────


def daily_text(status: PlatformStatus, yesterday: Day, now: datetime) -> str:
    return f"☀️ *Resumen diario*\n\n{status_text(status, now)}\n\n" + day_text(
        yesterday, f"📊 *Ayer*, {weekday_date(yesterday.start)}"
    )
