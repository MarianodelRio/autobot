"""Daily pack/channel health, and the operator's on-demand health command."""

from collections.abc import Collection
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import httpx
from django.conf import settings
from django.core.cache import cache
from django.utils import timezone
from pydantic import SecretStr

from autobot.channels.demo.doors import door
from autobot.channels.telegram.adapter import TelegramApiError, call
from autobot.channels.telegram.registration import expected_webhook_url
from autobot.runtime.context import CalendarFactory, build_context, google_calendar
from autobot.runtime.models import DEMO_CHANNELS, Channel
from autobot.tenancy.registry import LoadedTenant
from autobot.tenancy.schema import (
    TelegramChannel,
    TelegramSecrets,
    WhatsAppChannel,
    WhatsAppSecrets,
)

DAY_S = 86400
RETRY_FAILED_S = 15 * 60  # a one-off failure is rechecked sooner than a success


@dataclass(frozen=True)
class Issue:
    code: str
    message: str
    severity: str = "🟡"


def telegram_health(token: str, *, expected_url: str | None = None) -> list[Issue]:
    """`expected_url`: also fail if Telegram's own webhook isn't set to it —
    today's `telegram_health` only looked at recent delivery errors, so a bot that
    was never (or no longer) registered reported "ok" and never answered."""
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
    issues = []
    if expected_url is not None and info.get("url") != expected_url:
        # Never echo what Telegram reports back (it may hold a secret url).
        issues.append(
            Issue("telegram_webhook_unregistered", "El webhook no está registrado.", "🔴")
        )
    # Telegram retains the last historical error. Only errors in the last day signal
    # current health; never include last_error_message (it may contain a secret URL).
    since = timezone.now().timestamp() - DAY_S
    if any(
        isinstance(info.get(k), (int, float)) and info[k] > since
        for k in ("last_error_date", "last_synchronization_error_date")
    ):
        issues.append(
            Issue("telegram_webhook", "Telegram registra errores recientes del webhook.", "🔴")
        )
    return issues


def whatsapp_template_statuses(
    channel: WhatsAppChannel, secrets: WhatsAppSecrets, templates: Collection[tuple[str, str]]
) -> dict[tuple[str, str], str] | Issue:
    """The live status Meta reports for each of `templates` (`(name, language)`
    pairs); one missing from the result means Meta has never seen it. Used both by
    `whatsapp_health` (just whether all are `APPROVED`) and the "Alta" tab's own
    per-template detail."""
    headers = {"Authorization": f"Bearer {secrets.access_token.get_secret_value()}"}
    base = f"https://graph.facebook.com/{settings.WHATSAPP_GRAPH_VERSION}"
    try:
        with httpx.Client(timeout=10) as client:
            # A successful authorized read validates this token's access to this number.
            response = client.get(
                f"{base}/{channel.phone_number_id}", headers=headers, params={"fields": "id"}
            )
            if not response.is_success:
                return _graph_error(response)
            wanted = set(templates)
            found: dict[tuple[str, str], str] = {}
            after = None
            seen: set[str] = set()
            while wanted - found.keys():
                params = {"fields": "name,language,status", "limit": "100"}
                if after is not None:
                    params["after"] = after
                response = client.get(
                    f"{base}/{channel.waba_id}/message_templates", headers=headers, params=params
                )
                if not response.is_success:
                    return _graph_error(response)
                data = response.json()
                for row in data["data"]:
                    key = (row["name"], row["language"])
                    if key in wanted:
                        found[key] = row.get("status", "UNKNOWN")
                paging = data.get("paging", {})
                if not paging.get("next"):
                    break
                # Never follow Meta's next URL: it may contain an access token, and
                # a response must not redirect the authenticated client to another host.
                after = paging.get("cursors", {}).get("after")
                if not isinstance(after, str) or after in seen:
                    return Issue("whatsapp_response", "Paginación de Meta inválida.", "🔴")
                seen.add(after)
                if len(seen) > 100:
                    return Issue("whatsapp_response", "Demasiadas páginas de plantillas.", "🔴")
    except httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError:
        return Issue("whatsapp_unavailable", "No se puede consultar WhatsApp.", "🔴")
    return found


def whatsapp_health(
    channel: WhatsAppChannel, secrets: WhatsAppSecrets, templates: Collection[tuple[str, str]]
) -> list[Issue]:
    """Checked both for a tenant's own number (its pack's templates) and for the demo
    door's number (the templates of every active demo tenant's pack)."""
    result = whatsapp_template_statuses(channel, secrets, templates)
    if isinstance(result, Issue):
        return [result]
    approved = {key for key, status in result.items() if status == "APPROVED"}
    if set(templates) - approved:
        return [Issue("templates", "Faltan plantillas aprobadas del pack.")]
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
        if isinstance(tenant.secrets, TelegramSecrets) and isinstance(
            tenant.document.channel, TelegramChannel
        ):
            expected = expected_webhook_url(
                f"webhooks/telegram/{tenant.document.channel.public_id}"
            )
            issues.extend(
                telegram_health(tenant.secrets.bot_token.get_secret_value(), expected_url=expected)
            )
        elif isinstance(tenant.secrets, WhatsAppSecrets) and isinstance(
            tenant.document.channel, WhatsAppChannel
        ):
            templates = (
                {(t.name, t.language) for t in tenant.pack.templates} if tenant.pack else set()
            )
            issues.extend(whatsapp_health(tenant.document.channel, tenant.secrets, templates))
    return issues


@dataclass(frozen=True)
class HealthSnapshot:
    """What `daily` caches for a tenant (or a bot): when it was checked and what it found."""

    checked_at: datetime
    issues: list[Issue]


def cache_key(name: UUID | str) -> str:
    return f"health:{name}"


def read_snapshot(name: UUID | str) -> HealthSnapshot | None:
    """The cached result for `name`, or None when never checked (or unreadable). The cache
    holds a plain dict (`checked_at` as a timestamp), so other readers and older entries
    keep working."""
    cached = cache.get(cache_key(name))
    if not isinstance(cached, dict) or not isinstance(cached.get("checked_at"), int | float):
        return None
    return HealthSnapshot(
        checked_at=datetime.fromtimestamp(cached["checked_at"], tz=UTC),
        issues=list(cached.get("issues") or []),
    )


def write_snapshot(name: UUID | str, snapshot: HealthSnapshot) -> None:
    cache.set(
        cache_key(name),
        {"checked_at": snapshot.checked_at.timestamp(), "issues": snapshot.issues},
        timeout=None,
    )


def daily(name: UUID | str, check: Any, *, force: bool = False) -> list[Issue]:
    """Cache a success for 24 h; a failure only for `RETRY_FAILED_S` (~15 min), so a
    one-off failure does not stay cached a full day once the service is back.

    A separate checked_at controls refresh, so a stale failure remains observable if
    a checker is interrupted. Calls are serialized by ops_check's queueing lock.
    """
    now = timezone.now()
    snapshot = read_snapshot(name)
    stale = snapshot is None
    if snapshot is not None:
        ttl = RETRY_FAILED_S if snapshot.issues else DAY_S
        stale = (now - snapshot.checked_at).total_seconds() >= ttl
    if force or snapshot is None or stale:
        snapshot = HealthSnapshot(checked_at=now, issues=check())
        write_snapshot(name, snapshot)
    return list(snapshot.issues)
