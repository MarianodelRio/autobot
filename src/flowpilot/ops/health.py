"""Daily pack/channel health, and the operator's on-demand health command."""

from dataclasses import dataclass
from typing import Any
from uuid import UUID

import httpx
from django.conf import settings
from django.core.cache import cache
from django.utils import timezone
from pydantic import SecretStr

from flowpilot.channels.demo.doors import door
from flowpilot.channels.telegram.adapter import TelegramApiError, call
from flowpilot.runtime.context import CalendarFactory, build_context, google_calendar
from flowpilot.runtime.models import DEMO_CHANNELS, Channel
from flowpilot.tenancy.registry import LoadedTenant
from flowpilot.tenancy.schema import TelegramSecrets, WhatsAppSecrets

DAY_S = 86400


@dataclass(frozen=True)
class Issue:
    code: str
    message: str
    severity: str = "🟡"


def telegram_health(token: str, *, outbound_only: bool = False) -> list[Issue]:
    secrets = TelegramSecrets(bot_token=SecretStr(token), webhook_secret=SecretStr("-" * 32))
    try:
        with httpx.Client() as client:
            info = call(client, secrets, "getWebhookInfo", {})
    except TelegramApiError as exc:
        return [
            Issue(
                "auth" if exc.status in (401, 403) else "telegram_unavailable",
                "No se puede consultar el bot de Telegram.",
                "🔴",
            )
        ]
    if not isinstance(info, dict):
        return [Issue("telegram_response", "Respuesta de Telegram inválida.", "🔴")]
    if outbound_only and info.get("url"):
        return [Issue("notify_webhook", "El bot de avisos tiene un webhook activo.", "🔴")]
    # Telegram retains the last historical error. Only errors in the last day signal
    # current health; never include last_error_message (it may contain a secret URL).
    since = timezone.now().timestamp() - DAY_S
    if any(
        isinstance(info.get(k), (int, float)) and info[k] > since
        for k in ("last_error_date", "last_synchronization_error_date")
    ):
        return [Issue("telegram_webhook", "Telegram registra errores recientes del webhook.", "🔴")]
    return []


def whatsapp_health(tenant: LoadedTenant) -> list[Issue]:
    channel = tenant.file.channel
    if (
        channel is None
        or channel.type != "whatsapp"
        or not isinstance(tenant.secrets, WhatsAppSecrets)
    ):
        return []
    headers = {"Authorization": f"Bearer {tenant.secrets.access_token.get_secret_value()}"}
    base = f"https://graph.facebook.com/{settings.WHATSAPP_GRAPH_VERSION}"
    try:
        with httpx.Client(timeout=10) as client:
            # A successful authorized read validates this token's access to this number.
            response = client.get(
                f"{base}/{channel.phone_number_id}", headers=headers, params={"fields": "id"}
            )
            if not response.is_success:
                return [_graph_error(response)]
            required = (
                {(t.name, t.language) for t in tenant.pack.templates} if tenant.pack else set()
            )
            approved: set[tuple[str, str]] = set()
            after = None
            seen: set[str] = set()
            while required:
                params = {"fields": "name,language,status", "limit": "100"}
                if after is not None:
                    params["after"] = after
                response = client.get(
                    f"{base}/{channel.waba_id}/message_templates", headers=headers, params=params
                )
                if not response.is_success:
                    return [_graph_error(response)]
                data = response.json()
                for row in data["data"]:
                    if row.get("status") == "APPROVED":
                        approved.add((row["name"], row["language"]))
                paging = data.get("paging", {})
                if not paging.get("next"):
                    break
                # Never follow Meta's next URL: it may contain an access token, and
                # a response must not redirect the authenticated client to another host.
                after = paging.get("cursors", {}).get("after")
                if not isinstance(after, str) or after in seen:
                    return [Issue("whatsapp_response", "Paginación de Meta inválida.", "🔴")]
                seen.add(after)
                if len(seen) > 100:
                    return [Issue("whatsapp_response", "Demasiadas páginas de plantillas.", "🔴")]
            if required - approved:
                return [Issue("templates", "Faltan plantillas aprobadas del pack.")]
    except httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError:
        return [Issue("whatsapp_unavailable", "No se puede consultar WhatsApp.", "🔴")]
    return []


def _graph_error(response: httpx.Response) -> Issue:
    try:
        code = response.json().get("error", {}).get("code")
    except ValueError, AttributeError:
        code = None
    auth = response.status_code in (401, 403) or code == 190
    return Issue(
        "auth" if auth else "whatsapp_unavailable",
        "Token de WhatsApp inválido o sin acceso." if auth else "Consulta de Meta fallida.",
        "🔴",
    )


def tenant_health(
    tenant: LoadedTenant, *, calendars: CalendarFactory = google_calendar
) -> list[Issue]:
    issues: list[Issue] = []
    if tenant.is_degraded:
        issues.append(Issue("degraded", "El tenant está degradado.", "🔴"))
    if tenant.is_demo:
        channels = [channel for channel in DEMO_CHANNELS if door(channel) is not None]
    else:
        if not tenant.main_enabled:
            issues.append(
                Issue(
                    "channel_disabled", "El canal principal no tiene configuración completa.", "🔴"
                )
            )
        channels = [Channel.MAIN]
    if tenant.pack is not None and tenant.pack.health is not None and not tenant.is_degraded:
        for channel in channels:
            try:
                ctx = build_context(
                    tenant, channel, contact=None, state={}, event_id=None, calendars=calendars
                )
                for issue in tenant.pack.health(ctx):
                    issues.append(
                        Issue(
                            f"{channel}:{issue.code}",
                            "Comprobación de salud del pack fallida.",
                            "🔴" if issue.code == "calendar_unavailable" else "🟡",
                        )
                    )
            except Exception:
                issues.append(
                    Issue(
                        f"{channel}:pack_health", "No se puede comprobar la salud del pack.", "🔴"
                    )
                )
    if tenant.main_enabled:
        if isinstance(tenant.secrets, TelegramSecrets):
            issues.extend(telegram_health(tenant.secrets.bot_token.get_secret_value()))
        else:
            issues.extend(whatsapp_health(tenant))
    return issues


def daily(name: UUID | str, check: Any, *, force: bool = False) -> list[Issue]:
    """Cache results, including failures, for 24 h; results outlive their check deadline.

    A separate checked_at controls refresh, so a stale failure remains observable if
    a checker is interrupted. Calls are serialized by ops_check's queueing lock.
    """
    key = f"health:{name}"
    result = cache.get(key)
    now = timezone.now().timestamp()
    if force or not isinstance(result, dict) or now - result["checked_at"] >= DAY_S:
        issues = check()
        result = {"checked_at": now, "issues": issues}
        cache.set(key, result, timeout=None)
    return list(result["issues"])
