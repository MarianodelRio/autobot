"""The incident kinds and the open incidents (ADR-031).

An incident is an `ops_alert` row: one per open period of a (kind, tenant). Every kind
(an exact key or a prefix such as `queue_lag:`) is declared here with its nature:

- **condition** («está mal ahora»): ops_check opens it while the cause lasts and closes it
  (`auto`) when the cause is gone.
- **event** («pasó algo»): it stays open until a person reviews it («Lo he revisado»),
  which sets a review watermark. Only the cases after the watermark count; a newer one
  opens a new row that inherits the watermark («N nuevos desde tu revisión»).

The cases of an incident (sends, jobs, owner notices) are never copied into `ops_alert`
(it has no RLS): `ops/cases.py` computes them live from their tables. `open_incidents` is
the one list of open incidents behind the panel (Incidencias, sidebar, Resumen, tenant
level) and the notify bot (menu and daily summary)."""

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal
from uuid import UUID

from django.db import transaction
from django.db.models import Case, IntegerField, Max, Q, QuerySet, Value, When
from django.utils import timezone

from autobot.ops.models import OpsAlert
from autobot.ops.runbooks import runbook_path
from autobot.ops.send_errors import describe, known

type Nature = Literal["condition", "event"]
type Severity = Literal["critical", "warning", "notice", "info"]
type CaseType = Literal["send", "job", "notice"]
type Level = Literal["ok", "notice", "warning", "critical"]
type Closed = Literal["auto", "outage", "review", "info"]

SEVERITY_RANK: dict[str, int] = {"info": 0, "notice": 1, "warning": 2, "critical": 3}
# Severities that are pushed to Telegram when an incident opens (or escalates to them).
PUSHED: frozenset[str] = frozenset({"critical", "warning"})
# `resolved_by` of the platform's own closings; any other value is the reviewer.
PLATFORM_CLOSINGS: frozenset[str] = frozenset({"auto", "outage", "info"})
# With no previous review of a key, only the cases of the last 24 h count: a first run
# (or a new kind) never surfaces months of history at once.
BOOTSTRAP = timedelta(hours=24)

# Error classes of a rejected send that are an `outbound_rejected:<class>` incident.
# `auth` is not one: the `auth` condition already says the credential fails.
REJECTED_EXCLUDED: frozenset[str] = frozenset({"auth"})
# Recipient-side classes: nothing to repair on our side, so 🟡 (panel and daily summary).
REJECTED_NOTICE: frozenset[str] = frozenset({"blocked", "undeliverable", "marketing_declined"})

TASK_LABELS: dict[str, str] = {
    "process_event": "Procesar un mensaje",
    "apply_status": "Aplicar un estado de entrega",
    "send_message": "Enviar un mensaje",
    "send_notification": "Enviar un aviso al dueño",
    "route_demo_event": "Encaminar un mensaje de la demo",
    "dispatch_periodic": "Repartir una tarea periódica",
    "run_periodic": "Tarea periódica de un negocio",
    "retry_stalled_jobs": "Reintentar trabajos parados",
    "dispatch_owner_summaries": "Repartir los resúmenes mensuales",
    "send_owner_summary": "Resumen mensual al dueño",
    "reconcile_unknown": "Conciliar envíos ambiguos",
    "handle_owner_event": "Atender el chat del dueño",
    "ops_daily_summary": "Resumen diario de operación",
    "ops_check": "Comprobación de operación",
    "retention_cleanup": "Limpieza nocturna",
    "jobs_cleanup": "Limpieza de trabajos",
}


def task_label(task: str) -> str:
    return TASK_LABELS.get(task, task)


@dataclass(frozen=True)
class KindInfo:
    nature: Nature
    title: str
    advice: str
    cases: CaseType | None = None
    # Born resolved (e.g. `deploy_ok`): a one-off notice, never a problem to track.
    informational: bool = False


type _Text = str | Callable[[str], str]


@dataclass(frozen=True)
class _Spec:
    nature: Nature
    title: _Text
    advice: _Text = ""
    cases: CaseType | None = None
    informational: bool = False

    def info(self, suffix: str) -> KindInfo:
        title = self.title(suffix) if callable(self.title) else self.title
        advice = self.advice(suffix) if callable(self.advice) else self.advice
        return KindInfo(self.nature, title, advice, self.cases, self.informational)


def _rejected_title(cls: str) -> str:
    return f"Envíos rechazados: {describe(known(cls)).title.lower()}"


def _rejected_advice(cls: str) -> str:
    return describe(known(cls)).advice


C: Nature = "condition"
E: Nature = "event"
_RESOURCES = "Mira el apartado del runbook."

# Exact keys.
KINDS: dict[str, _Spec] = {
    # ── Conditions ──
    "inbound_delay": _Spec(
        C,
        "Mensajes entrantes con retraso",
        "Los mensajes de clientes esperan más de 2 minutos en la cola: revisa worker-inbound.",
    ),
    "queue_lag_unknown": _Spec(
        C,
        "Atraso de las colas sin medir",
        "La consulta del atraso falló o tardó demasiado: puede haber una cola muy acumulada.",
    ),
    "check_failed": _Spec(
        C,
        "Comprobación del negocio fallida",
        "La comprobación periódica de este negocio falla: mira los logs. Sus otras"
        " incidencias siguen como estaban hasta que vuelva a completarse.",
    ),
    "inbound_stuck": _Spec(
        C,
        "Mensajes entrantes atascados",
        "Eventos entrantes pendientes sin trabajo: se reencolan solos durante una hora.",
    ),
    "outbound_stuck": _Spec(
        C,
        "Envíos pendientes sin trabajo",
        "Envíos pendientes demasiado antiguos para reencolarlos solos: revisa la cola outbound.",
    ),
    "outbound_ambiguous": _Spec(
        C,
        "Envíos sin confirmar",
        "No se sabe si llegaron y la conciliación no lo resolvió: marca cada uno como"
        " enviado, reenvíalo o descártalo.",
        cases="send",
    ),
    "provider_outage": _Spec(
        C,
        "Proveedor de mensajería caído",
        "Los envíos esperan y se reintentan solos cuando vuelve.",
    ),
    "calendar_outage": _Spec(
        C,
        "Google Calendar caído",
        "Las reservas se reintentan solas; las incidencias de cada negocio quedan agrupadas"
        " en esta.",
    ),
    "owner_unlinked": _Spec(
        C,
        "Dueño sin chat de avisos",
        "El dueño no ha conectado su chat: sus avisos se retienen 2 h y luego caducan."
        " Envíale de nuevo la invitación.",
        cases="notice",
    ),
    "config_stale": _Spec(
        C,
        "Configuración desactualizada",
        "Algún proceso no ha recargado la configuración: si no se corrige solo, reinícialo.",
    ),
    "registry": _Spec(
        C,
        "Configuraciones ilegibles",
        "Hay configuraciones de negocios o secretos que no se pueden leer: esos negocios no"
        " atienden.",
    ),
    "tenant_unavailable": _Spec(
        C,
        "Negocio no disponible",
        "Configuración degradada o canal sin secretos: el negocio no atiende por su canal.",
    ),
    "auth": _Spec(
        C,
        "Credencial del canal rechazada",
        "El proveedor rechaza la credencial del canal principal: revisa el token.",
    ),
    "tenant_silent": _Spec(
        C,
        "Negocio en silencio",
        "Sin mensajes de clientes desde hace más de lo habitual: revisa que el canal sigue"
        " conectado.",
    ),
    "webhook_unsubscribed": _Spec(
        C,
        "Webhook sin suscripción",
        "El proveedor no entrega los mensajes a la plataforma: vuelve a registrar el webhook.",
    ),
    "webhook_errors": _Spec(
        C, "Errores en el webhook", "Telegram informa de errores o retraso al entregarlo."
    ),
    "number_quality": _Spec(
        C,
        "Calidad del número baja",
        "WhatsApp ha bajado la calidad del número: revisa qué se envía antes de que limite.",
    ),
    "disk": _Spec(C, "Disco por encima del 80 %", "Libera espacio antes de que se llene."),
    "disk_critical": _Spec(C, "Disco casi lleno", "Por encima del 95 %: libera espacio ya."),
    "inodes": _Spec(C, "Inodos por encima del 80 %", _RESOURCES),
    "inodes_critical": _Spec(C, "Inodos casi agotados", _RESOURCES),
    "memory_high": _Spec(C, "Memoria alta sostenida", _RESOURCES),
    "load_high": _Spec(C, "Carga alta sostenida", _RESOURCES),
    "swap_high": _Spec(C, "Swap en uso", _RESOURCES),
    "backup_stale": _Spec(C, "Backup atrasado o fallido", "Revisa `journalctl -u autobot-backup`."),
    "backup_prune_overdue": _Spec(
        C, "Copias sin caducar", "Hace más de 10 días: ejecuta `make backup-prune`."
    ),
    "tls_expiring": _Spec(C, "Certificado a punto de caducar", _RESOURCES),
    "tls_expiring_critical": _Spec(C, "Certificado a punto de caducar", _RESOURCES),
    "tls_invalid": _Spec(C, "Certificado no válido", _RESOURCES),
    "containers_stale": _Spec(
        C,
        "Estado de los contenedores sin actualizar",
        "El timer que lo escribe no corre: revisa `autobot-containers.timer`.",
    ),
    "containers_restore": _Spec(
        C, "Restauración a medias", "Existe var/.restore-incomplete: termina la restauración."
    ),
    # ── Events ──
    "notification_failed": _Spec(
        E,
        "Avisos al dueño perdidos",
        "Avisos fallidos, ambiguos o caducados: el dueño no los recibió y no se reenvían solos.",
        cases="notice",
    ),
    "billing": _Spec(
        E,
        "Umbral de mensajes facturables superado",
        "Los mensajes facturables de WhatsApp de este mes pasan del umbral del negocio. Se"
        " avisa una vez al mes.",
    ),
    "billing:demo_wa": _Spec(
        E,
        "Umbral de la demo de WhatsApp superado",
        "Los mensajes facturables de la puerta WhatsApp de demo pasan del umbral mensual.",
    ),
    "deploy_aborted": _Spec(
        E,
        "Despliegue abortado",
        "Se abortó antes de cambiar la imagen: revisa los logs del despliegue.",
    ),
    "deploy_rollback": _Spec(
        E,
        "Despliegue revertido",
        "El despliegue falló y se volvió a la versión anterior: revisa el estado de salud.",
    ),
    # ── Informational (born resolved) ──
    "deploy_ok": _Spec(E, "Desplegado", informational=True),
    "deploy_caddy_reload": _Spec(E, "Caddy sin recargar", informational=True),
    "deploy_https_check": _Spec(E, "HTTPS sin responder tras desplegar", informational=True),
}

# Keys with a variable suffix, matched by prefix (the longest first).
PREFIXES: dict[str, _Spec] = {
    "queue_lag:": _Spec(C, lambda s: f"Cola {s} atrasada", "Mira qué trabajo la ocupa."),
    "auth:": _Spec(
        C,
        lambda s: f"Credencial del bot de demo rechazada ({s})",
        "Revisa el token de la puerta de demo en el .env del servidor.",
    ),
    "bot:": _Spec(C, lambda s: f"Bot de la plataforma ({s})", "Revisa el bot y su webhook."),
    "errors:": _Spec(
        C, lambda s: f"Errores seguidos ({s})", "El negocio acumula tres errores seguidos."
    ),
    "health:": _Spec(C, lambda s: f"Salud del negocio ({s})", "Mira el detalle del negocio."),
    "calendar:": _Spec(
        C,
        lambda s: f"Calendar sin acceso ({s})",
        "Revisa que el calendario sigue compartido con la cuenta de servicio.",
    ),
    "sweep:": _Spec(
        C,
        lambda s: f"Barrido sin completarse ({s})",
        "El barrido lleva más de una hora sin acabar.",
    ),
    "container_down:": _Spec(C, lambda s: f"Contenedor {s} caído", "Mira sus logs y reinícialo."),
    "container_unhealthy:": _Spec(
        C, lambda s: f"Contenedor {s} con el healthcheck fallando", "Mira sus logs."
    ),
    "container_image:": _Spec(
        C, lambda s: f"Contenedor {s} con otra imagen", "No coincide con la versión desplegada."
    ),
    "container_unexpected:": _Spec(
        C, lambda s: f"Contenedor {s} no esperado", "¿Huérfano de un despliegue? Elimínalo."
    ),
    "outbound_rejected:": _Spec(E, _rejected_title, _rejected_advice, cases="send"),
    "failed_job:": _Spec(
        E,
        lambda s: f"Trabajo fallido: {task_label(s)}",
        "Si la tarea es idempotente, reinténtala; si no, revisa los logs.",
        cases="job",
    ),
    "container_restarted:": _Spec(
        E, lambda s: f"Contenedor {s} reiniciado", "Mira sus logs (¿se quedó sin memoria?)."
    ),
}


def kind_info(kind: str) -> KindInfo:
    """The registry entry of a kind; an unknown one is a condition titled by its key."""
    if kind in KINDS:
        return KINDS[kind].info("")
    for prefix in sorted(PREFIXES, key=len, reverse=True):
        if kind.startswith(prefix):
            return PREFIXES[prefix].info(kind.removeprefix(prefix))
    return KindInfo("condition", kind, "")


def is_event(kind: str) -> bool:
    return kind_info(kind).nature == "event"


def rejected_kind(cls: str) -> str:
    return f"outbound_rejected:{cls}"


def failed_job_kind(task: str) -> str:
    return f"failed_job:{task}"


# ── Severity ────────────────────────────────────────────────────────────────


def as_severity(value: str) -> Severity:
    """A stored severity as the closed type of the API (an unexpected one reads `warning`)."""
    return value if value in SEVERITY_RANK else "warning"  # type: ignore[return-value]


def level(severities: Iterable[str]) -> Level:
    """The worst of `severities`: `info` (and anything unknown) never raises it."""
    rank = max((SEVERITY_RANK.get(s, 0) for s in severities), default=0)
    return ("ok", "notice", "warning", "critical")[rank]


def counts(severities: Iterable[str]) -> dict[str, int]:
    """How many of each severity, `critical`, `warning` and `notice` always present."""
    out = {"critical": 0, "warning": 0, "notice": 0}
    for severity in severities:
        if severity in out:
            out[severity] += 1
    return out


# ── Open incidents ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Incident:
    row: OpsAlert
    info: KindInfo
    # A reopened event (a previous period of it was reviewed): its cases are all new.
    reopened: bool

    @property
    def severity(self) -> str:
        return self.row.severity

    @property
    def tenant_id(self) -> UUID | None:
        return self.row.tenant_id

    @property
    def title(self) -> str:
        return self.info.title

    @property
    def new_since_review(self) -> int | None:
        return self.row.case_count if self.reopened else None

    @property
    def runbook(self) -> str | None:
        return runbook_path(self.row.kind)


def ordered(qs: QuerySet[OpsAlert]) -> QuerySet[OpsAlert]:
    """Most severe first, then the most recent."""
    return qs.annotate(
        severity_rank=Case(
            When(severity="critical", then=Value(0)),
            When(severity="warning", then=Value(1)),
            When(severity="notice", then=Value(2)),
            default=Value(3),
            output_field=IntegerField(),
        )
    ).order_by("severity_rank", "-last_seen_at", "-id")


def open_incidents(*, using: str = "default", tenant_id: UUID | None = None) -> list[Incident]:
    """Every open incident, most severe and most recent first. `using`: `default` in the
    workers (fp_app), `owner` in the panel. `tenant_id`: only that tenant's."""
    qs = OpsAlert.objects.using(using).filter(resolved_at__isnull=True)
    if tenant_id is not None:
        qs = qs.filter(tenant_id=tenant_id)
    rows = list(ordered(qs))
    reviewed = _reviewed_keys(rows, using)
    return [
        Incident(
            row=row,
            info=kind_info(row.kind),
            reopened=(row.kind, row.tenant_id) in reviewed,
        )
        for row in rows
    ]


def _reviewed_keys(rows: Sequence[OpsAlert], using: str) -> set[tuple[str, UUID | None]]:
    """The (kind, tenant) keys among `rows`' events that a person has reviewed before."""
    kinds = {row.kind for row in rows if not row.auto_resolves}
    if not kinds:
        return set()
    return set(
        OpsAlert.objects.using(using)
        .filter(kind__in=kinds, resolved_at__isnull=False, auto_resolves=False)
        .exclude(resolved_by__in=PLATFORM_CLOSINGS)
        .exclude(resolved_by="")
        .values_list("kind", "tenant_id")
        .distinct()
    )


def closed_how(row: OpsAlert) -> Closed:
    if row.resolved_by in PLATFORM_CLOSINGS:
        return row.resolved_by  # type: ignore[return-value]
    return "review"


# ── Review watermarks ───────────────────────────────────────────────────────


type Key = tuple[str, UUID | None]


def watermarks(kinds: Q, *, using: str = "default") -> dict[Key, datetime]:
    """The latest review watermark of each (kind, tenant) matching `kinds`."""
    rows = (
        OpsAlert.objects.using(using)
        .filter(kinds, review_watermark__isnull=False)
        .values("kind", "tenant_id")
        .annotate(at=Max("review_watermark"))
    )
    return {(row["kind"], row["tenant_id"]): row["at"] for row in rows}


def bound(marks: dict[Key, datetime], kind: str, tenant_id: UUID | None, now: datetime) -> datetime:
    """The time after which a case of this event counts."""
    return marks.get((kind, tenant_id)) or now - BOOTSTRAP


def inherited_watermark(
    kind: str, tenant_id: UUID | None, now: datetime, *, using: str = "default"
) -> datetime:
    """The watermark of a new open period: the latest one of the key, or the bootstrap."""
    latest = (
        OpsAlert.objects.using(using)
        .filter(kind=kind, tenant_id=tenant_id, review_watermark__isnull=False)
        .aggregate(at=Max("review_watermark"))["at"]
    )
    return latest or now - BOOTSTRAP


# ── Review («Lo he revisado») ───────────────────────────────────────────────


@dataclass(frozen=True)
class ReviewResult:
    ok: bool
    message: str


def review(alert_id: UUID, *, actor: str) -> ReviewResult:
    """Close an open event: its watermark becomes its newest case seen by ops_check (never
    `now`, which would hide a case that arrived while the person read the screen), and a
    case after it opens a new period. Sends nothing to Telegram. Audited."""
    from autobot.ops.audit import record

    with transaction.atomic(using="owner"):
        alert = OpsAlert.objects.using("owner").select_for_update().filter(pk=alert_id).first()
        if alert is None:
            return ReviewResult(False, "not_found")
        if alert.resolved_at is not None:
            return ReviewResult(False, "La incidencia ya está cerrada.")
        if alert.auto_resolves or not is_event(alert.kind):
            return ReviewResult(False, "Esta incidencia se cierra sola cuando se corrige la causa.")
        now = timezone.now()
        watermark = alert.last_case_at or alert.last_seen_at or now
        if alert.review_watermark is not None:
            watermark = max(watermark, alert.review_watermark)
        alert.review_watermark = min(watermark, now)
        alert.resolved_at = now
        alert.resolved_by = actor
        alert.save(using="owner", update_fields=["review_watermark", "resolved_at", "resolved_by"])
        record(
            actor=actor,
            action="incident.review",
            summary="Operador revisa una incidencia.",
            tenant_id=alert.tenant_id,
            target_type="ops_alert",
            target_id=str(alert.pk),
            details={"kind": alert.kind, "cases": alert.case_count},
        )
    return ReviewResult(True, "Incidencia revisada.")
