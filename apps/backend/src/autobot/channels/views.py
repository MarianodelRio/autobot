"""Webhooks of each tenant's main channel.

Order: tenant (404), body size (400), authenticity (401, counted for the limit of that
IP and that tenant; once the limit is reached the answer is 429), JSON (400), offboarded
(200 without saving), then each item is saved and queued (200). The signature is checked
before the body is parsed. No external calls: only the in-memory registry and the
database.

The invalid-signature limit is per (IP, tenant): the addresses of Meta and Telegram are
shared by every business, so one tenant with a wrong secret must never block the others.
It only ever answers 429 to a request whose signature is *not* valid: a valid one is
always accepted, whatever was counted before.
"""

import json
import logging
from collections.abc import Callable
from typing import Any

from django.db import DataError
from django.db import Error as DatabaseError
from django.http import HttpRequest, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods, require_POST
from procrastinate.exceptions import ProcrastinateException

from autobot.channels.adapters import TELEGRAM, WHATSAPP
from autobot.channels.base import ParsedItem
from autobot.channels.ratelimit import WindowLimiter, client_ip
from autobot.ops.logging import bind
from autobot.runtime.inbound import store
from autobot.tenancy.registry import LoadedTenant, get_registry
from autobot.tenancy.schema import (
    TelegramChannel,
    TelegramSecrets,
    WhatsAppChannel,
    WhatsAppSecrets,
)

log = logging.getLogger(__name__)

MAX_BODY = 256 * 1024

limiter = WindowLimiter()  # invalid signatures per (IP, route: tenant or bot)


def limiter_key(request: HttpRequest, route: str) -> str:
    """`route` names what the request is for (`whatsapp:<public_id>`, `telegram-demo`…)."""
    return f"{client_ip(request)}:{route}"


def reject_unauthenticated(request: HttpRequest, route: str) -> HttpResponse:
    """The answer to a request whose signature or secret is wrong: 401, counted for
    (IP, route); 429 once that count reaches the limit (and then not counted again)."""
    key = limiter_key(request, route)
    if limiter.blocked(key):
        return HttpResponse(status=429)
    limiter.record(key)
    return HttpResponse(status=401)


def body_too_large(request: HttpRequest) -> bool:
    try:
        declared = int(request.META.get("CONTENT_LENGTH") or 0)
    except ValueError:
        return True
    return declared > MAX_BODY or len(request.body) > MAX_BODY


def json_object(request: HttpRequest) -> dict[str, Any] | None:
    """The request's JSON object, or None if the body is not one."""
    try:
        body = json.loads(request.body)
    except ValueError, RecursionError:
        return None
    return body if isinstance(body, dict) else None


def storage_failure(error: Exception, what: str) -> HttpResponse:
    """The answer when saving an authentic update failed. A database `DataError` (a body
    the database refuses to hold) is permanent: the provider's retries would fail the
    same way, so it is dropped (200) and logged without its content. Anything else
    (connection, queue) is transient: 503, so the provider retries."""
    if isinstance(error, DataError):
        log.error("%s dropped: the database refused it (%s)", what, type(error).__name__)
        return HttpResponse(status=200)
    log.error("%s not saved: %s", what, type(error).__name__)
    return HttpResponse(status=503)


@csrf_exempt
@require_http_methods(["GET", "POST"])
def whatsapp(request: HttpRequest, public_id: str) -> HttpResponse:
    try:
        tenant = main_channel_tenant("whatsapp", public_id)
    except DatabaseError:
        log.error("Tenant registry unavailable")
        return HttpResponse(status=503)
    if tenant is None:
        return HttpResponse(status=404)
    bind(tenant=tenant.slug, channel="main")
    channel, secrets = tenant.document.channel, tenant.secrets
    assert isinstance(channel, WhatsAppChannel) and isinstance(secrets, WhatsAppSecrets)
    route = f"whatsapp:{public_id}"
    if request.method == "GET":
        return handle_meta_handshake(request, secrets, route=route, who=f"tenant {tenant.slug}")
    return receive(
        request,
        route=route,
        who=f"tenant {tenant.slug}",
        verify=lambda: WHATSAPP.verify(request, channel, secrets),
        handle=lambda body: accept(tenant, body, lambda b: WHATSAPP.parse(b, channel)),
    )


@csrf_exempt
@require_POST
def telegram(request: HttpRequest, public_id: str) -> HttpResponse:
    try:
        tenant = main_channel_tenant("telegram", public_id)
    except DatabaseError:
        log.error("Tenant registry unavailable")
        return HttpResponse(status=503)
    if tenant is None:
        return HttpResponse(status=404)
    bind(tenant=tenant.slug, channel="main")
    channel, secrets = tenant.document.channel, tenant.secrets
    assert isinstance(channel, TelegramChannel) and isinstance(secrets, TelegramSecrets)
    return receive(
        request,
        route=f"telegram:{public_id}",
        who=f"tenant {tenant.slug}",
        verify=lambda: TELEGRAM.verify(request, channel, secrets),
        handle=lambda body: accept(tenant, body, lambda b: TELEGRAM.parse(b, channel)),
    )


def main_channel_tenant(kind: str, public_id: str) -> LoadedTenant | None:
    """The tenant whose main channel this is, if that channel is enabled (also what
    `telegram_poll` requires: the same rules as the webhook)."""
    tenant = get_registry().by_public_id.get((kind, public_id))
    if tenant is None or not tenant.main_enabled or tenant.secrets is None:
        return None
    return tenant


def handle_meta_handshake(
    request: HttpRequest, secrets: WhatsAppSecrets, *, route: str, who: str
) -> HttpResponse:
    """Meta's `GET` subscription handshake: the challenge echoed back, or 403 (counted
    for the invalid-signature limit; 429 once it is reached)."""
    challenge = WHATSAPP.verify_subscription(request.GET.dict(), secrets)
    if challenge is None:
        log.warning("WhatsApp verification refused for %s", who)
        response = reject_unauthenticated(request, route)
        return HttpResponse(status=403) if response.status_code == 401 else response
    return HttpResponse(challenge, content_type="text/plain")


def receive(
    request: HttpRequest,
    *,
    route: str,
    who: str,
    verify: Callable[[], bool],
    handle: Callable[[dict[str, Any]], None],
) -> HttpResponse:
    """The steps every webhook POST shares, in this order: size (400), authenticity (401
    or 429), JSON (400), then `handle(body)` saves what is authentic (200; 503 if saving
    failed transiently). `who` names the webhook in logs, never the sender."""
    if body_too_large(request):
        return HttpResponse(status=400)
    if not verify():
        log.warning("Invalid webhook signature for %s", who)
        return reject_unauthenticated(request, route)
    body = json_object(request)
    if body is None:
        return HttpResponse(status=400)
    try:
        handle(body)
    except (DatabaseError, ProcrastinateException) as e:  # the provider retries
        return storage_failure(e, f"Webhook of {who}")
    return HttpResponse(status=200)


def accept(
    tenant: LoadedTenant,
    body: dict[str, Any],
    parse: Callable[[dict[str, Any]], list[ParsedItem]],
) -> None:
    """What an authentic body of a tenant's main channel becomes: nothing if the tenant
    is offboarded, otherwise its items saved and queued. The one entry shared by the
    webhooks and `telegram_poll`."""
    if tenant.document.status == "offboarded":
        return
    store(tenant, parse(body))
