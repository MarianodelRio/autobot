"""The onboarding steps (ADR-014, ADR-027): assembled from the services already built,
instead of a new hook per pack or channel. Each step names the Configuración section it
belongs to, where the panel shows it next to the fields it depends on.
"""

from collections.abc import Collection, Iterable
from datetime import datetime
from typing import TYPE_CHECKING, Any

from django.conf import settings
from ninja import Schema

from autobot.channels.adapters import endpoint
from autobot.channels.base import InboundItem, parse_stored
from autobot.channels.whatsapp import registration as meta
from autobot.ops.audit import record_tenant
from autobot.ops.health import Issue, whatsapp_template_statuses
from autobot.ops.status import tenant_status
from autobot.panel.errors import ApiError
from autobot.panel.services._common import get_tenant_or_404
from autobot.panel.services.tenants import tenant_dataset_status
from autobot.runtime.context import CalendarUnavailable, build_context
from autobot.runtime.models import Channel, InboundEvent
from autobot.tenancy import activation, store
from autobot.tenancy.registry import LoadedTenant, get_registry, source_from_dir
from autobot.tenancy.schema import TelegramChannel, WhatsAppChannel, WhatsAppSecrets
from core.errors import PermanentError, TransientError
from integrations.google_calendar.client import service_account_email
from packs import registry as pack_registry  # read `PACKS` at call time: tests replace it

if TYPE_CHECKING:
    from autobot.channels.whatsapp.registration import NumberStatus


class SetupValue(Schema):
    label: str
    value: str
    copiable: bool = True


class TesterCandidate(Schema):
    id: str
    display: str
    received_at: str


class SetupAction(Schema):
    label: str
    needs_pin: bool = False
    confirm: bool = False


class SetupStepOut(Schema):
    key: str
    # The Configuración section the step shows in (`forms.ui_schema` groups); a key
    # with no section of that name shows at the top, next to the activation progress.
    section: str
    label: str
    why: str
    state: str  # "ok" | "pending" | "error" | "n/a"
    blocking: bool
    detail: str
    values: list[SetupValue] = []
    checkable: bool = False
    tester_candidates: list[TesterCandidate] = []
    action: SetupAction | None = None


def _state(ok: bool) -> str:
    return "ok" if ok else "pending"


def _channel_values(channel: Any) -> list[SetupValue]:
    if channel is None:
        return []
    if isinstance(channel, WhatsAppChannel):
        webhook_url = f"{settings.PUBLIC_URL}/webhooks/whatsapp/{channel.public_id}"
        return [
            SetupValue(label="App de Meta", value=channel.app_id or "—"),
            SetupValue(label="WABA", value=channel.waba_id or "—"),
            SetupValue(label="Teléfono (Meta)", value=channel.phone_number_id or "—"),
            SetupValue(label="Teléfono público", value=channel.display_phone or "—"),
            SetupValue(label="URL del webhook (para el panel de Meta)", value=webhook_url),
        ]
    if isinstance(channel, TelegramChannel):
        return [SetupValue(label="Usuario del bot", value=channel.bot_username or "—")]
    return []


_TEMPLATE_STATUS_ES = {
    "APPROVED": "Aprobada",
    "PENDING": "Pendiente de Meta",
    "REJECTED": "Rechazada",
    "PAUSED": "Pausada",
    "DISABLED": "Deshabilitada",
}


def _template_values(
    tenant: LoadedTenant, statuses: dict[tuple[str, str], str] | None = None
) -> list[SetupValue]:
    if tenant.pack is None:
        return []
    values = []
    for template in tenant.pack.templates:
        key = (template.name, template.language)
        if statuses is None:
            status = "sin comprobar"
        else:
            raw = statuses.get(key)
            status = _TEMPLATE_STATUS_ES.get(raw, raw) if raw else "no encontrada en Meta"
        values.append(
            SetupValue(
                label=f"{template.name} ({template.language}) — {status}",
                value=template.text,
            )
        )
    return values


def tenant_setup(slug: str) -> list[SetupStepOut]:
    """Only what is already cached or in the database — never calls a provider.
    `tenant_setup_check` does that, one step at a time."""
    tenant = get_tenant_or_404(slug)
    items = {item.key: item for item in activation.checklist(slug, refresh=False).items}
    channel = tenant.document.channel
    steps = [
        SetupStepOut(
            key="document",
            section="business",
            label="Documento",
            why="Un documento inválido o degradado no se puede activar.",
            state=_state(items["document"].ok),
            blocking=items["document"].blocking,
            detail=items["document"].detail,
        ),
        SetupStepOut(
            key="channel",
            section="channel",
            label="Canal",
            why="Sin los ids completos no hay enlace público ni QR.",
            state=_state(items["channel"].ok),
            blocking=items["channel"].blocking,
            detail=items["channel"].detail,
            values=_channel_values(channel),
        ),
        SetupStepOut(
            key="secrets",
            section="channel",
            label="Secretos",
            why="Sin secretos legibles el canal no puede enviar ni recibir.",
            state=_state(items["secrets"].ok),
            blocking=items["secrets"].blocking,
            detail=items["secrets"].detail,
        ),
    ]
    # Telegram has no step of its own for its webhook: the Canal section shows its
    # registration status with «Registrar webhook» (`GET/POST .../telegram-webhook`),
    # and an unregistered webhook already fails «Salud del canal» (critical), which is
    # what blocks the activation.
    if isinstance(channel, WhatsAppChannel):
        steps.extend(_whatsapp_steps(tenant, channel))
        steps.append(
            SetupStepOut(
                key="templates",
                section="channel",
                label="Plantillas de WhatsApp",
                why="Sin plantillas aprobadas no se pueden enviar mensajes proactivos.",
                state=_state(items["templates"].ok),
                blocking=items["templates"].blocking,
                detail=items["templates"].detail,
                values=_template_values(tenant),
                checkable=True,
            )
        )
    steps.append(
        SetupStepOut(
            key="health",
            section="channel",
            label="Salud del canal",
            why="Un problema crítico de salud bloquea la activación.",
            state=_state(items["health"].ok),
            blocking=items["health"].blocking,
            detail=items["health"].detail,
            checkable=True,
        )
    )
    steps.append(
        SetupStepOut(
            key="privacy",
            section="legal",
            label="Privacidad y atención",
            why="El primer mensaje del bot cita el enlace a la política de privacidad y "
            "«PERSONA» da el contacto para hablar con alguien; sin ellos no se puede activar.",
            state=_state(items["privacy"].ok),
            blocking=items["privacy"].blocking,
            detail="Rellena «Enlace a la política de privacidad» y «Contacto para hablar con "
            "una persona» en esta misma sección y guarda.",
        )
    )
    steps.append(
        SetupStepOut(
            key="tester",
            section="people",
            label="Mensaje de un tester",
            why="Confirma que el canal principal responde de verdad antes de activar.",
            state=_state(items["tester"].ok),
            blocking=items["tester"].blocking,
            detail=items["tester"].detail,
            tester_candidates=_tester_candidates(tenant),
        )
    )
    steps.append(
        SetupStepOut(
            key="owner",
            section="people",
            label="Dueño",
            why="Sin enlazar, el dueño no recibe avisos de citas ni resúmenes.",
            state=_state(items["owner"].ok),
            blocking=items["owner"].blocking,
            detail=items["owner"].detail,
        )
    )
    if tenant.document.pack == "salon":
        email = (
            service_account_email(settings.GOOGLE_SERVICE_ACCOUNT_FILE)
            if settings.GOOGLE_SERVICE_ACCOUNT_FILE
            else None
        )
        config = tenant.document.config if isinstance(tenant.document.config, dict) else {}
        calendar_id = config.get("calendar_id") if isinstance(config, dict) else None
        steps.append(
            SetupStepOut(
                key="calendar",
                section="calendar",
                label="Calendario",
                why="Sin permiso de escritura en el calendario del negocio no se pueden"
                " guardar citas.",
                state="pending",
                blocking=False,
                detail="Comparte el calendario con la cuenta de servicio y pulsa"
                " «Comprobar» para probar la escritura.",
                values=[
                    SetupValue(label="Cuenta de servicio", value=email or "—"),
                    SetupValue(label="Calendario del negocio", value=str(calendar_id or "—")),
                ],
                checkable=True,
            )
        )
    steps.extend(_dataset_steps(slug, tenant))
    return steps


def pick_tester_candidates(
    items: Iterable[tuple[InboundItem, datetime]], testers: Collection[str], *, limit: int
) -> list[TesterCandidate]:
    """From senders (newest first) keeps those not already in `testers`, one per person,
    up to `limit`. Pure: no database, no provider."""
    candidates: list[TesterCandidate] = []
    seen: set[str] = set()
    for item, received_at in items:
        phone = item.phone.removeprefix("+") if item.phone else None
        if item.external_id in testers or (phone is not None and phone in testers):
            continue
        tester_id = phone or item.external_id
        if tester_id in seen:
            continue
        seen.add(tester_id)
        candidates.append(
            TesterCandidate(
                id=tester_id,
                display=phone or f"id {item.external_id}",
                received_at=received_at.isoformat(),
            )
        )
        if len(candidates) >= limit:
            break
    return candidates


def _ignored_senders(tenant: LoadedTenant, *, scan: int = 50) -> list[tuple[InboundItem, datetime]]:
    """The senders of the last `scan` ignored messages, newest first: each event's own
    stored payload re-parsed with the tenant's real channel (inbound events keep no link
    to a contact record, ADR-009)."""
    ep = endpoint(tenant, Channel.MAIN)
    events = (
        InboundEvent.objects.using("owner")
        .filter(
            tenant_id=tenant.id,
            channel=Channel.MAIN,
            kind=InboundEvent.Kind.MESSAGE,
            status=InboundEvent.Status.IGNORED,
        )
        .order_by("-received_at")[:scan]
    )
    senders: list[tuple[InboundItem, datetime]] = []
    for event in events:
        if not isinstance(event.payload, dict):
            continue
        try:
            item = parse_stored(ep.adapter, event.payload, ep.channel)
        except ValueError, KeyError, TypeError:
            continue
        if isinstance(item, InboundItem):
            senders.append((item, event.received_at))
    return senders


def _tester_candidates(tenant: LoadedTenant, *, limit: int = 5) -> list[TesterCandidate]:
    """Recent senders ignored for not being in `testers.main`."""
    if tenant.document.channel is None:
        return []
    return pick_tester_candidates(
        _ignored_senders(tenant), set(tenant.document.testers.main), limit=limit
    )


def tenant_setup_add_tester(slug: str, tester_id: str, *, actor: str) -> SetupStepOut:
    tenant = get_tenant_or_404(slug)
    if tenant.version is None:
        raise ApiError("bad_request", "El negocio está degradado.", 400)
    doc = tenant.document.model_dump(mode="json")
    main = doc.get("testers", {}).get("main", [])
    if tester_id in main:
        raise ApiError("bad_request", "Ese tester ya está añadido.", 400)
    # Only someone who really wrote and was ignored: never an id typed or crafted by hand.
    if tester_id not in {c.id for c in _tester_candidates(tenant, limit=50)}:
        raise ApiError("bad_request", "Ese id no es un candidato reciente.", 400)
    doc.setdefault("testers", {})["main"] = [*main, tester_id]
    store.publish(
        slug,
        document=doc,
        base_version=tenant.version,
        actor=actor,
        comment="Tester añadido desde Configuración",
    )
    record_tenant(actor, "tenant.setup_add_tester", tenant, "Tester añadido desde Configuración")
    get_registry(force=True)
    for step in tenant_setup(slug):
        if step.key == "tester":
            return step
    raise ApiError("not_found", "No se encuentra el paso de testers", 404)  # pragma: no cover


def _dataset_names(tenant: LoadedTenant) -> tuple[str, ...]:
    """The dataset names a pack's own template declares : its directory
    layout is the only canonical source of them. Looked up by name, never via
    `tenant.pack` — a tenant missing its dataset is degraded (no bound pack), which
    is exactly when this step matters most."""
    pack = pack_registry.PACKS.get(tenant.document.pack)
    if pack is None or pack.template is None:
        return ()
    return tuple(sorted(source_from_dir(pack.template).datasets))


def _dataset_steps(slug: str, tenant: LoadedTenant) -> list[SetupStepOut]:
    steps = []
    for name in _dataset_names(tenant):
        status = tenant_dataset_status(slug, name)
        if status.version is None:
            detail = "No tiene datos cargados: elige uno en la biblioteca."
        else:
            detail = f"Versión {status.version}, de «{status.source_name}»."
            if status.newer_version_available:
                detail += (
                    f" Hay una versión más nueva ({status.newer_version_available})"
                    " en la biblioteca."
                )
        steps.append(
            SetupStepOut(
                key=f"dataset:{name}",
                section="datasets",
                label="Horarios" if name == "timetable" else name,
                why="Sin datos cargados el negocio no puede responder con ellos.",
                state=_state(status.version is not None),
                blocking=False,
                detail=detail,
            )
        )
    return steps


def tenant_setup_check(slug: str, step: str, *, actor: str) -> SetupStepOut:
    """Runs one step's real check against the provider, outside any transaction,
    and audits the result."""
    tenant = get_tenant_or_404(slug)
    steps = {item.key: item for item in tenant_setup(slug)}
    current = steps.get(step)
    if current is None or not current.checkable:
        raise ApiError("bad_request", "Ese paso no se puede comprobar", 400)

    if step == "health":
        result = _check_health(tenant, current)
    elif step == "calendar":
        result = _check_calendar(tenant, current)
    elif step == "templates":
        result = _check_templates(tenant, current)
    elif step in _WHATSAPP_STEPS:
        result = _check_whatsapp(tenant, current)
    else:  # pragma: no cover - current.checkable already restricts this
        raise ApiError("bad_request", "Ese paso no se puede comprobar", 400)

    record_tenant(
        actor,
        "tenant.setup_check",
        tenant,
        f"Comprobación de alta: {step}",
        step=step,
        state=result.state,
    )
    return result


def _check_health(tenant: LoadedTenant, current: SetupStepOut) -> SetupStepOut:
    # The same forced check activation runs, so what is shown is what would block it.
    item = {i.key: i for i in activation.checklist(tenant.slug).items}["health"]
    reasons = tenant_status(tenant).reasons
    detail = "Sin problemas críticos." if item.ok else "; ".join(reasons) or "Hay un problema."
    return current.model_copy(update={"state": "ok" if item.ok else "error", "detail": detail})


def _check_calendar(tenant: LoadedTenant, current: SetupStepOut) -> SetupStepOut:
    config = tenant.document.config if isinstance(tenant.document.config, dict) else {}
    if not config.get("calendar_id"):
        return current.model_copy(
            update={"state": "error", "detail": "Falta calendar_id en la config."}
        )
    try:
        ctx = build_context(tenant, Channel.MAIN, contact=None, state={}, event_id=None)
        # `ctx.calendar` is already bound to the right one; never reach into
        # `packs.salon` directly (autobot.* only talks to a pack through its own
        # `Pack` hooks and `PackContext`, per import-linter).
        ctx.calendar.check_write_access()
    except (PermanentError, TransientError, CalendarUnavailable) as error:
        return current.model_copy(
            update={
                "state": "error",
                "detail": f"No se pudo escribir en el calendario: {type(error).__name__}.",
            }
        )
    return current.model_copy(
        update={"state": "ok", "detail": "Escritura confirmada (evento de prueba borrado)."}
    )


def _check_templates(tenant: LoadedTenant, current: SetupStepOut) -> SetupStepOut:
    if tenant.pack is None or not isinstance(tenant.secrets, WhatsAppSecrets):
        return current.model_copy(
            update={"state": "error", "detail": "Faltan secretos legibles de WhatsApp."}
        )
    channel = tenant.document.channel
    if not isinstance(channel, WhatsAppChannel):
        return current.model_copy(update={"state": "error", "detail": "Este canal no es WhatsApp."})
    templates = {(t.name, t.language) for t in tenant.pack.templates}
    result = whatsapp_template_statuses(channel, tenant.secrets, templates)
    if isinstance(result, Issue):
        return current.model_copy(update={"state": "error", "detail": result.message})
    approved = {key for key, status in result.items() if status == "APPROVED"}
    ok = templates <= approved
    detail = (
        "Todas las plantillas del pack están aprobadas."
        if ok
        else "Faltan plantillas por aprobar: revisa el estado de cada una."
    )
    return current.model_copy(
        update={
            "state": "ok" if ok else "error",
            "detail": detail,
            "values": _template_values(tenant, result),
        }
    )


# ── WhatsApp: finish connecting the number from the panel (ADR-016) ───────────

_WHATSAPP_STEPS: dict[str, tuple[str, str, SetupAction]] = {
    "whatsapp_webhook": (
        "Webhook de la app",
        "Sin el webhook configurado en la app de Meta, ningún mensaje llega a la plataforma.",
        SetupAction(label="Configurar webhook"),
    ),
    "whatsapp_number": (
        "Número registrado",
        "Un número sin registrar en la Cloud API no puede enviar ni recibir mensajes.",
        SetupAction(label="Registrar número", needs_pin=True),
    ),
    "whatsapp_subscription": (
        "App suscrita a la cuenta",
        "Sin la app suscrita a la cuenta de WhatsApp, Meta no le entrega los mensajes.",
        SetupAction(label="Suscribir app", confirm=True),
    ),
}


def _whatsapp_ready(tenant: LoadedTenant) -> tuple[WhatsAppChannel, WhatsAppSecrets] | str:
    """The channel and its secrets, or a detail saying what is missing."""
    channel = tenant.document.channel
    if not isinstance(channel, WhatsAppChannel):
        return "Este canal no es WhatsApp."
    missing = [
        name for name in ("app_id", "waba_id", "phone_number_id") if not getattr(channel, name)
    ]
    secrets = tenant.secrets
    if not isinstance(secrets, WhatsAppSecrets):
        missing.append("secretos legibles")
    if missing or not isinstance(secrets, WhatsAppSecrets):
        return f"Falta: {', '.join(missing)}."
    return channel, secrets


def _whatsapp_steps(tenant: LoadedTenant, channel: WhatsAppChannel) -> list[SetupStepOut]:
    ready = _whatsapp_ready(tenant)
    steps = []
    for key, (label, why, action) in _WHATSAPP_STEPS.items():
        values = []
        if key == "whatsapp_webhook":
            url = f"{settings.PUBLIC_URL}/webhooks/whatsapp/{channel.public_id}"
            values = [SetupValue(label="URL del webhook", value=url)]
        steps.append(
            SetupStepOut(
                key=key,
                section="channel",
                label=label,
                why=why,
                state="pending",
                blocking=False,
                detail=ready
                if isinstance(ready, str)
                else "Pulsa «Comprobar» para consultarlo en Meta.",
                values=values,
                checkable=True,
                action=None if isinstance(ready, str) else action,
            )
        )
    return steps


def _check_whatsapp(tenant: LoadedTenant, current: SetupStepOut) -> SetupStepOut:
    ready = _whatsapp_ready(tenant)
    if isinstance(ready, str):
        return current.model_copy(update={"state": "error", "detail": ready})
    channel, secrets = ready
    try:
        if current.key == "whatsapp_webhook":
            ok = meta.app_webhook_status(channel, secrets, meta.webhook_url(channel))
            detail = (
                "Configurado con esta URL y el campo «messages»."
                if ok
                else "No está configurado con esta URL: pulsa «Configurar webhook»."
            )
            return current.model_copy(update={"state": _error_unless(ok), "detail": detail})
        if current.key == "whatsapp_number":
            return _number_result(current, meta.number_status(channel, secrets))
        ok = meta.app_subscribed(channel, secrets)
        detail = "Suscrita." if ok else "No está suscrita: pulsa «Suscribir app»."
        return current.model_copy(update={"state": _error_unless(ok), "detail": detail})
    except meta.RegistrationError as error:
        return current.model_copy(update={"state": "error", "detail": error.message})


def _error_unless(ok: bool) -> str:
    return "ok" if ok else "error"


def _number_result(current: SetupStepOut, status: NumberStatus) -> SetupStepOut:
    values = [
        *current.values,
        SetupValue(label="Estado en Meta", value=status.status or "—", copiable=False),
        SetupValue(label="Nombre visible", value=status.name_status or "—", copiable=False),
        SetupValue(label="Calidad", value=status.quality_rating or "—", copiable=False),
    ]
    if not status.registered:
        state, detail = "error", "No está registrado en la Cloud API: pulsa «Registrar número»."
    elif status.status not in (None, "CONNECTED"):
        state, detail = "error", "Registrado, pero Meta no lo da por conectado."
    else:
        state, detail = "ok", "Registrado en la Cloud API."
    return current.model_copy(update={"state": state, "detail": detail, "values": values})


def tenant_setup_action(slug: str, step: str, pin: str | None, *, actor: str) -> SetupStepOut:
    """Runs one step's write against Meta, outside any transaction, and audits the
    outcome (never the PIN). An ambiguous write is reported, never retried."""
    tenant = get_tenant_or_404(slug)
    if not isinstance(tenant.document.channel, WhatsAppChannel):
        raise ApiError("bad_request", "El canal no es WhatsApp", 400)
    current = {item.key: item for item in tenant_setup(slug)}.get(step)
    ready = _whatsapp_ready(tenant)
    if current is None or current.action is None or isinstance(ready, str):
        raise ApiError("bad_request", "Ese paso no tiene acción", 400)
    channel, secrets = ready
    try:
        if step == "whatsapp_webhook":
            meta.configure_app_webhook(channel, secrets, meta.webhook_url(channel))
            outcome, detail = "done", "Webhook configurado: Meta ha verificado la URL."
        elif step == "whatsapp_number":
            if pin is None or not meta.PIN.fullmatch(pin):
                raise ApiError("bad_request", "El PIN debe tener exactamente 6 dígitos.", 400)
            if meta.register_number(channel, secrets, pin):
                outcome, detail = "done", "Número registrado en la Cloud API."
            else:
                outcome, detail = "already", "Ya estaba registrado: no se ha repetido el registro."
        else:
            meta.subscribe_app(channel, secrets)
            outcome, detail = "done", "App suscrita: el número ya puede recibir mensajes."
    except meta.RegistrationError as error:
        _record_action(tenant, step, error.outcome, actor)
        raise ApiError("unavailable", error.message, 502) from None
    _record_action(tenant, step, outcome, actor)
    return current.model_copy(update={"state": "ok", "detail": detail})


def _record_action(tenant: LoadedTenant, step: str, outcome: str, actor: str) -> None:
    record_tenant(
        actor, "tenant.setup_action", tenant, f"Acción de alta: {step}", step=step, outcome=outcome
    )
