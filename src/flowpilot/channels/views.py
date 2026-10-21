"""Webhooks of each tenant's main channel (design.md §7.1, §13).

Order: IP blocked by invalid signatures (429), tenant (404), body size (400), authenticity
(401, counted for the IP limit), JSON (400), offboarded (200 without saving), then each
item is saved and queued (200). The signature is checked before the body is parsed. No
external calls: only the in-memory registry and the database.
"""

import json
import logging
from collections.abc import Callable
from typing import Any

from django.db import Error as DatabaseError
from django.http import HttpRequest, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods, require_POST
from procrastinate.exceptions import ProcrastinateException

from flowpilot.channels.adapters import TELEGRAM, WHATSAPP
from flowpilot.channels.base import ParsedItem
from flowpilot.channels.ratelimit import WindowLimiter, client_ip
from flowpilot.runtime.inbound import store
from flowpilot.tenancy.registry import LoadedTenant, get_registry
from flowpilot.tenancy.schema import (
    TelegramChannel,
    TelegramSecrets,
    WhatsAppChannel,
    WhatsAppSecrets,
)

log = logging.getLogger(__name__)

MAX_BODY = 64 * 1024

limiter = WindowLimiter()  # invalid signatures per IP


@csrf_exempt
@require_http_methods(["GET", "POST"])
def whatsapp(request: HttpRequest, public_id: str) -> HttpResponse:
    if limiter.blocked(client_ip(request)):
        return HttpResponse(status=429)
    tenant = _tenant("whatsapp", public_id)
    if tenant is None:
        return HttpResponse(status=404)
    channel, secrets = tenant.file.channel, tenant.secrets
    assert isinstance(channel, WhatsAppChannel) and isinstance(secrets, WhatsAppSecrets)
    if request.method == "GET":  # Meta's subscription handshake
        challenge = WHATSAPP.verify_subscription(request.GET.dict(), secrets)
        if challenge is None:
            limiter.record(client_ip(request))
            log.warning("WhatsApp verification refused for tenant %s", tenant.slug)
            return HttpResponse(status=403)
        return HttpResponse(challenge, content_type="text/plain")
    return _receive(
        request,
        tenant,
        verify=lambda: WHATSAPP.verify(request, channel, secrets),
        parse=lambda body: WHATSAPP.parse(body, channel),
    )


@csrf_exempt
@require_POST
def telegram(request: HttpRequest, public_id: str) -> HttpResponse:
    if limiter.blocked(client_ip(request)):
        return HttpResponse(status=429)
    tenant = _tenant("telegram", public_id)
    if tenant is None:
        return HttpResponse(status=404)
    channel, secrets = tenant.file.channel, tenant.secrets
    assert isinstance(channel, TelegramChannel) and isinstance(secrets, TelegramSecrets)
    return _receive(
        request,
        tenant,
        verify=lambda: TELEGRAM.verify(request, channel, secrets),
        parse=lambda body: TELEGRAM.parse(body, channel),
    )


def _tenant(kind: str, public_id: str) -> LoadedTenant | None:
    """The tenant whose main channel this is, if that channel is enabled."""
    tenant = get_registry().by_public_id.get((kind, public_id))
    if tenant is None or not tenant.main_enabled or tenant.secrets is None:
        return None
    return tenant


def _receive(
    request: HttpRequest,
    tenant: LoadedTenant,
    *,
    verify: Callable[[], bool],
    parse: Callable[[dict[str, Any]], list[ParsedItem]],
) -> HttpResponse:
    try:
        declared = int(request.META.get("CONTENT_LENGTH") or 0)
    except ValueError:
        return HttpResponse(status=400)
    if declared > MAX_BODY or len(request.body) > MAX_BODY:
        return HttpResponse(status=400)
    if not verify():
        limiter.record(client_ip(request))
        log.warning("Invalid webhook signature for tenant %s", tenant.slug)
        return HttpResponse(status=401)
    try:
        body = json.loads(request.body)
    except ValueError:
        return HttpResponse(status=400)
    if not isinstance(body, dict):
        return HttpResponse(status=400)
    if tenant.file.status == "offboarded":
        return HttpResponse(status=200)
    try:
        store(tenant, parse(body))
    except (DatabaseError, ProcrastinateException) as e:  # the provider retries (§7.7)
        log.error("Webhook of tenant %s not saved: %s", tenant.slug, type(e).__name__)
        return HttpResponse(status=503)
    return HttpResponse(status=200)
