"""The "Alta" tab (ADR-014): one step-by-step view assembled from the services
C1-C15 and D1-D4 already built, instead of a new hook per pack or channel.
"""

from typing import Any

from django.conf import settings
from ninja import Schema

from autobot.ops.audit import record
from autobot.panel.errors import ApiError
from autobot.tenancy import activation
from autobot.tenancy.registry import LoadedTenant, get_registry
from autobot.tenancy.schema import TelegramChannel, WhatsAppChannel


class SetupValue(Schema):
    label: str
    value: str
    copiable: bool = True


class SetupStepOut(Schema):
    key: str
    label: str
    why: str
    state: str  # "ok" | "pending" | "error" | "n/a"
    blocking: bool
    detail: str
    values: list[SetupValue] = []
    checkable: bool = False


def _tenant(slug: str) -> LoadedTenant:
    tenant = get_registry().by_slug.get(slug)
    if tenant is None:
        tenant = get_registry(force=True).by_slug.get(slug)
    if tenant is None:
        raise ApiError("not_found", "No se encuentra el negocio", 404)
    return tenant


def _state(ok: bool) -> str:
    return "ok" if ok else "pending"


def _channel_values(channel: Any) -> list[SetupValue]:
    if channel is None:
        return []
    if isinstance(channel, WhatsAppChannel):
        return [
            SetupValue(label="App de Meta", value=channel.app_id or "—"),
            SetupValue(label="WABA", value=channel.waba_id or "—"),
            SetupValue(label="Teléfono (Meta)", value=channel.phone_number_id or "—"),
            SetupValue(label="Teléfono público", value=channel.display_phone or "—"),
        ]
    if isinstance(channel, TelegramChannel):
        return [SetupValue(label="Usuario del bot", value=channel.bot_username or "—")]
    return []


def tenant_setup(slug: str) -> list[SetupStepOut]:
    """Only what is already cached or in the database — never calls a provider.
    `tenant_setup_check` does that, one step at a time."""
    tenant = _tenant(slug)
    items = {item.key: item for item in activation.checklist(slug).items}
    channel = tenant.document.channel
    steps = [
        SetupStepOut(
            key="document",
            label="Documento",
            why="Un documento inválido o degradado no se puede activar.",
            state=_state(items["document"].ok),
            blocking=items["document"].blocking,
            detail=items["document"].detail,
        ),
        SetupStepOut(
            key="channel",
            label="Canal",
            why="Sin los ids completos no hay enlace público ni QR.",
            state=_state(items["channel"].ok),
            blocking=items["channel"].blocking,
            detail=items["channel"].detail,
            values=_channel_values(channel),
        ),
        SetupStepOut(
            key="secrets",
            label="Secretos",
            why="Sin secretos legibles el canal no puede enviar ni recibir.",
            state=_state(items["secrets"].ok),
            blocking=items["secrets"].blocking,
            detail=items["secrets"].detail,
        ),
    ]
    if isinstance(channel, TelegramChannel):
        from autobot.channels.telegram.registration import expected_webhook_url

        expected = expected_webhook_url(f"webhooks/telegram/{channel.public_id}")
        steps.append(
            SetupStepOut(
                key="webhook",
                label="Webhook de Telegram",
                why="Sin el webhook registrado, Telegram nunca entrega los mensajes.",
                state="pending",
                blocking=True,
                detail="Pulsa «Comprobar» para consultarlo en Telegram.",
                values=[SetupValue(label="URL esperada", value=expected or "—", copiable=True)],
                checkable=True,
            )
        )
    if isinstance(channel, WhatsAppChannel):
        steps.append(
            SetupStepOut(
                key="templates",
                label="Plantillas de WhatsApp",
                why="Sin plantillas aprobadas no se pueden enviar mensajes proactivos.",
                state=_state(items["templates"].ok),
                blocking=items["templates"].blocking,
                detail=items["templates"].detail,
            )
        )
    steps.append(
        SetupStepOut(
            key="health",
            label="Salud del canal",
            why="Un problema crítico de salud bloquea la activación.",
            state=_state(items["health"].ok),
            blocking=items["health"].blocking,
            detail=items["health"].detail,
        )
    )
    steps.append(
        SetupStepOut(
            key="tester",
            label="Mensaje de un tester",
            why="Confirma que el canal principal responde de verdad antes de activar.",
            state=_state(items["tester"].ok),
            blocking=items["tester"].blocking,
            detail=items["tester"].detail,
        )
    )
    steps.append(
        SetupStepOut(
            key="owner",
            label="Dueño",
            why="Sin enlazar, el dueño no recibe avisos de citas ni resúmenes.",
            state=_state(items["owner"].ok),
            blocking=items["owner"].blocking,
            detail=items["owner"].detail,
        )
    )
    if tenant.document.pack == "salon":
        from integrations.google_calendar.client import service_account_email

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
                label="Calendario (D1-D4)",
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


def _dataset_names(tenant: LoadedTenant) -> tuple[str, ...]:
    """The dataset names a pack's own template declares (C22): its directory
    layout is the only canonical source of them. Looked up by name, never via
    `tenant.pack` — a tenant missing its dataset is degraded (no bound pack), which
    is exactly when this step matters most."""
    from packs.registry import PACKS

    pack = PACKS.get(tenant.document.pack)
    if pack is None or pack.template is None:
        return ()
    from autobot.tenancy.registry import source_from_dir

    return tuple(sorted(source_from_dir(pack.template).datasets))


def _dataset_steps(slug: str, tenant: LoadedTenant) -> list[SetupStepOut]:
    from autobot.panel.services.tenants import tenant_dataset_status

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
    tenant = _tenant(slug)
    steps = {item.key: item for item in tenant_setup(slug)}
    current = steps.get(step)
    if current is None or not current.checkable:
        raise ApiError("bad_request", "Ese paso no se puede comprobar", 400)

    if step == "webhook":
        from autobot.channels.telegram.registration import is_webhook_registered

        registered = is_webhook_registered(slug)
        state = "ok" if registered else "error" if registered is False else "pending"
        detail = (
            "Registrado."
            if registered
            else "No está registrado: usa «Registrar webhook» en Configuración."
            if registered is False
            else "No se pudo comprobar."
        )
        result = current.model_copy(update={"state": state, "detail": detail})
    elif step == "calendar":
        result = _check_calendar(tenant, current)
    else:  # pragma: no cover - current.checkable already restricts this
        raise ApiError("bad_request", "Ese paso no se puede comprobar", 400)

    record(
        actor=actor,
        action="tenant.setup_check",
        tenant_id=tenant.id,
        target_type="tenant",
        target_id=str(tenant.id),
        summary=f"Comprobación de alta: {step}",
        details={"step": step, "state": result.state},
    )
    return result


def _check_calendar(tenant: LoadedTenant, current: SetupStepOut) -> SetupStepOut:
    from autobot.runtime.context import CalendarUnavailable, build_context
    from autobot.runtime.models import Channel
    from core.errors import PermanentError, TransientError

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
