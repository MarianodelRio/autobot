"""Daily pack/channel health, and the operator's on-demand health command."""

import hashlib
import logging
import socket
import ssl
import time
from collections.abc import Callable, Collection, Iterable
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
from autobot.channels.whatsapp import registration
from autobot.runtime.context import CalendarFactory, build_context, google_calendar
from autobot.runtime.models import DEMO_CHANNELS, Channel
from autobot.tenancy.registry import LoadedTenant
from autobot.tenancy.schema import (
    TelegramChannel,
    TelegramSecrets,
    WhatsAppChannel,
    WhatsAppSecrets,
)

log = logging.getLogger(__name__)

DAY_S = 86400
TLS_WARNING_DAYS = 14
TLS_CRITICAL_DAYS = 3
TLS_TIMEOUT_S = 5.0
RETRY_FAILED_S = 15 * 60  # a one-off failure is rechecked sooner than a success
SPREAD_WINDOW_S = 2 * 3600  # the per-tenant offset of the daily check, up to this
CHANNEL_CHECK_TIMEOUT_S = 5
# Telegram queues updates it cannot deliver; a long queue means the webhook is not
# reaching us (a healthy bot has a handful at most).
TELEGRAM_BACKLOG = 100
# Number states in which Meta does not let the number send normally.
BLOCKED_NUMBER_STATUSES = frozenset(
    {"RESTRICTED", "FLAGGED", "BANNED", "DISCONNECTED", "OFFLINE", "DELETED"}
)


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
    pending = info.get("pending_update_count")
    if isinstance(pending, int) and pending > TELEGRAM_BACKLOG:
        issues.append(
            Issue(
                "telegram_webhook_backlog",
                "Telegram tiene muchas actualizaciones sin entregar al webhook.",
                "🟠",
            )
        )
    return issues


def whatsapp_channel_health(channel: WhatsAppChannel, secrets: WhatsAppSecrets) -> list[Issue]:
    """Read-only Graph checks of a tenant's own number: our app is still subscribed to
    its WABA (otherwise Meta stops sending webhooks and nobody notices) and the number is
    in good standing. A failed read is reported as unavailable so `daily` retries it
    soon instead of caching a blind "ok" for a day."""
    if not (channel.app_id and channel.waba_id and channel.phone_number_id):
        return []
    issues: list[Issue] = []
    try:
        if not registration.app_subscribed(channel, secrets, CHANNEL_CHECK_TIMEOUT_S):
            issues.append(
                Issue(
                    "webhook_unsubscribed",
                    "La app de Meta ya no está suscrita a la cuenta de WhatsApp: no llegarán"
                    " mensajes.",
                    "🔴",
                )
            )
        number = registration.number_status(channel, secrets, CHANNEL_CHECK_TIMEOUT_S)
    except registration.RegistrationError as exc:
        if exc.outcome == "auth":
            return [Issue("auth", "Token de WhatsApp inválido o sin acceso.", "🔴")]
        return [Issue("whatsapp_unavailable", "No se puede consultar WhatsApp.", "🔴")]
    tier = number.messaging_limit_tier or "desconocido"
    if number.quality_rating == "RED" or number.status in BLOCKED_NUMBER_STATUSES:
        issues.append(
            Issue(
                "number_quality",
                f"Número de WhatsApp restringido o con calidad baja (estado {number.status},"
                f" calidad {number.quality_rating}, límite {tier}).",
                "🔴",
            )
        )
    elif number.quality_rating == "YELLOW":
        issues.append(
            Issue(
                "number_quality",
                f"La calidad del número de WhatsApp ha bajado a media (límite {tier}).",
                "🟠",
            )
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
            seen = {i.code for i in issues}
            issues.extend(
                i
                for i in whatsapp_channel_health(tenant.document.channel, tenant.secrets)
                if i.code not in seen
            )
    return issues


@dataclass(frozen=True)
class HealthSnapshot:
    """What `daily` caches for a tenant (or a bot): when it was checked and what it found."""

    checked_at: datetime
    issues: list[Issue]


def cache_key(name: UUID | str) -> str:
    return f"health:{name}"


def _snapshot_from(cached: Any) -> HealthSnapshot | None:
    if not isinstance(cached, dict) or not isinstance(cached.get("checked_at"), int | float):
        return None
    return HealthSnapshot(
        checked_at=datetime.fromtimestamp(cached["checked_at"], tz=UTC),
        issues=list(cached.get("issues") or []),
    )


def read_snapshot(name: UUID | str) -> HealthSnapshot | None:
    """The cached result for `name`, or None when never checked (or unreadable). The cache
    holds a plain dict (`checked_at` as a timestamp), so other readers and older entries
    keep working."""
    return _snapshot_from(cache.get(cache_key(name)))


def read_snapshots(names: Iterable[UUID | str]) -> dict[UUID | str, HealthSnapshot | None]:
    """`read_snapshot` for many names in one cache round trip (the cache is a database
    table: reading them one by one costs a query each)."""
    names = list(names)
    found = cache.get_many([cache_key(name) for name in names])
    return {name: _snapshot_from(found.get(cache_key(name))) for name in names}


def write_snapshot(name: UUID | str, snapshot: HealthSnapshot) -> None:
    cache.set(
        cache_key(name),
        {"checked_at": snapshot.checked_at.timestamp(), "issues": snapshot.issues},
        timeout=None,
    )


def spread_s(name: UUID | str) -> int:
    """A stable offset of this tenant (or bot) within `SPREAD_WINDOW_S`, from a hash of its
    id: the same every run and every process."""
    digest = hashlib.sha256(str(name).encode()).digest()
    return int.from_bytes(digest[:4]) % SPREAD_WINDOW_S


def success_ttl_s(name: UUID | str) -> int:
    """How long a clean result is trusted: a day minus the tenant's offset, so the tenants
    checked together on a cold start (or after an outage) drift apart in the next days
    instead of coming due in the same minute every day."""
    return DAY_S - spread_s(name)


def ttl_s(name: UUID | str, snapshot: HealthSnapshot) -> int:
    return RETRY_FAILED_S if snapshot.issues else success_ttl_s(name)


def overdue_s(name: UUID | str, snapshot: HealthSnapshot | None, now: datetime) -> float:
    """How late is the check of `name` (negative: not due yet). A never-checked one is the
    most overdue, in the stable order of its offset."""
    if snapshot is None:
        return float(10 * DAY_S - spread_s(name))
    return (now - snapshot.checked_at).total_seconds() - ttl_s(name, snapshot)


def _monotonic() -> float:
    return time.monotonic()


class HealthBudget:
    """The seconds of external health checks one `ops_check` run may spend. A due check
    that finds it spent is left for the next run (they come every five minutes), so the
    first run after a cold start, or a restart that lost the cache, does not take
    minutes with every tenant due at once."""

    def __init__(self, seconds: float, clock: Callable[[], float] | None = None) -> None:
        self._seconds = seconds
        self._clock = clock or _monotonic
        self._spent = 0.0
        self.skipped = 0

    @property
    def exhausted(self) -> bool:
        return self._spent >= self._seconds

    def charge(self, seconds: float) -> None:
        self._spent += seconds

    def now(self) -> float:
        return self._clock()


def _cert_not_after(host: str, port: int, timeout: float) -> datetime:
    """The `notAfter` of the certificate `host:port` serves, validated like a browser
    would (chain and name): an expired or wrong one raises `ssl.SSLCertVerificationError`."""
    context = ssl.create_default_context()
    with (
        socket.create_connection((host, port), timeout=timeout) as raw,
        context.wrap_socket(raw, server_hostname=host) as tls,
    ):
        cert = tls.getpeercert()
    if not cert or "notAfter" not in cert:
        raise ValueError("no certificate")
    return datetime.fromtimestamp(ssl.cert_time_to_seconds(str(cert["notAfter"])), UTC)


def tls_health(
    host: str, port: int = 443, *, now: datetime | None = None, timeout: float = TLS_TIMEOUT_S
) -> list[Issue]:
    """Days left of the public certificate (Caddy renews it ~30 days before expiry, so
    under 14 means the renewal is failing). A network error is not an issue of its own
    (the container and proxy alerts cover an unreachable proxy) and never raises: it is
    only logged. Call it outside any transaction."""
    now = now or timezone.now()
    try:
        not_after = _cert_not_after(host, port, timeout)
    except ssl.SSLCertVerificationError:
        return [Issue("tls_invalid", "El certificado público no es válido o ha caducado.", "🔴")]
    except (OSError, ssl.SSLError, ValueError) as exc:
        log.warning("tls check of %s skipped: %s", host, type(exc).__name__)
        return []
    days = (not_after - now).total_seconds() / DAY_S
    if days < TLS_CRITICAL_DAYS:
        return [
            Issue(
                "tls_expiring_critical",
                f"El certificado público caduca en {max(days, 0):.0f} días.",
                "🔴",
            )
        ]
    if days < TLS_WARNING_DAYS:
        return [Issue("tls_expiring", f"El certificado público caduca en {days:.0f} días.", "🟠")]
    return []


def daily(
    name: UUID | str, check: Any, *, force: bool = False, budget: HealthBudget | None = None
) -> list[Issue]:
    """Cache a success for about a day (see `success_ttl_s`); a failure only for
    `RETRY_FAILED_S` (~15 min), so a one-off failure does not stay cached a full day once
    the service is back.

    A separate checked_at controls refresh, so a stale failure remains observable if
    a checker is interrupted. Calls are serialized by ops_check's queueing lock. With a
    `budget`, a due check is skipped (the cached result, if any, is returned) once the
    run has spent it; the next run picks it up.
    """
    now = timezone.now()
    snapshot = read_snapshot(name)
    stale = snapshot is None or (now - snapshot.checked_at).total_seconds() >= ttl_s(name, snapshot)
    if force or stale:
        if budget is not None and not force:
            if budget.exhausted:
                budget.skipped += 1
                return list(snapshot.issues) if snapshot is not None else []
            started = budget.now()
            issues = check()
            budget.charge(budget.now() - started)
        else:
            issues = check()
        snapshot = HealthSnapshot(checked_at=now, issues=issues)
        write_snapshot(name, snapshot)
    assert snapshot is not None
    return list(snapshot.issues)
