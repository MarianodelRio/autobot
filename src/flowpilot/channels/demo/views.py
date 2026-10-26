"""`POST /webhooks/telegram-demo` and `GET|POST /webhooks/whatsapp-demo`: the demo
bot's door webhooks.

Same checks as a tenant's webhook (IP limit, size, signature/secret before parsing,
JSON), but neither knows the tenant yet: they only write `demo_event`, which has no
RLS. Off (404) without the door's credentials: local development uses `telegram_poll`
for Telegram; the WhatsApp door only runs on the server (a Meta number has one webhook
URL).
"""

import json
import logging

from django.conf import settings
from django.db import Error as DatabaseError
from django.http import HttpRequest, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods, require_POST
from procrastinate.exceptions import ProcrastinateException

from flowpilot.channels import views as webhooks
from flowpilot.channels.adapters import TELEGRAM, WHATSAPP
from flowpilot.channels.base import InboundItem, StatusItem
from flowpilot.channels.demo.doors import door
from flowpilot.channels.demo.selector import route_demo_status, store_event
from flowpilot.channels.ratelimit import client_ip
from flowpilot.ops.logging import bind
from flowpilot.runtime.models import Channel

log = logging.getLogger(__name__)


@csrf_exempt
@require_POST
def telegram_demo(request: HttpRequest) -> HttpResponse:
    bind(channel=str(Channel.DEMO_TG))
    ip = client_ip(request)
    if webhooks.limiter.blocked(ip):
        return HttpResponse(status=429)
    door_ = door(Channel.DEMO_TG)
    if not settings.DEMO_TELEGRAM_WEBHOOK_SECRET or door_ is None:
        return HttpResponse(status=404)
    try:
        declared = int(request.META.get("CONTENT_LENGTH") or 0)
    except ValueError:
        return HttpResponse(status=400)
    if declared > webhooks.MAX_BODY or len(request.body) > webhooks.MAX_BODY:
        return HttpResponse(status=400)
    if not TELEGRAM.verify(request, None, door_.secrets):
        webhooks.limiter.record(ip)
        log.warning("Invalid demo Telegram webhook secret")
        return HttpResponse(status=401)
    try:
        body = json.loads(request.body)
    except ValueError:
        return HttpResponse(status=400)
    if not isinstance(body, dict):
        return HttpResponse(status=400)
    try:
        for item in TELEGRAM.parse(body, None):
            if isinstance(item, InboundItem):
                store_event(door_, item)
    except (DatabaseError, ProcrastinateException) as e:
        log.error("Demo Telegram update not saved: %s", type(e).__name__)
        return HttpResponse(status=503)
    return HttpResponse(status=200)


@csrf_exempt
@require_http_methods(["GET", "POST"])
def whatsapp_demo(request: HttpRequest) -> HttpResponse:
    bind(channel=str(Channel.DEMO_WA))
    ip = client_ip(request)
    if webhooks.limiter.blocked(ip):
        return HttpResponse(status=429)
    door_ = door(Channel.DEMO_WA)
    if door_ is None:
        return HttpResponse(status=404)
    if request.method == "GET":  # Meta's subscription handshake
        challenge = WHATSAPP.verify_subscription(request.GET.dict(), door_.secrets)
        if challenge is None:
            webhooks.limiter.record(ip)
            log.warning("Demo WhatsApp verification refused")
            return HttpResponse(status=403)
        return HttpResponse(challenge, content_type="text/plain")
    try:
        declared = int(request.META.get("CONTENT_LENGTH") or 0)
    except ValueError:
        return HttpResponse(status=400)
    if declared > webhooks.MAX_BODY or len(request.body) > webhooks.MAX_BODY:
        return HttpResponse(status=400)
    if not WHATSAPP.verify(request, door_.description, door_.secrets):
        webhooks.limiter.record(ip)
        log.warning("Invalid demo WhatsApp webhook signature")
        return HttpResponse(status=401)
    try:
        body = json.loads(request.body)
    except ValueError:
        return HttpResponse(status=400)
    if not isinstance(body, dict):
        return HttpResponse(status=400)
    try:
        for item in WHATSAPP.parse(body, door_.description):
            if isinstance(item, InboundItem):
                store_event(door_, item)
            elif isinstance(item, StatusItem):
                route_demo_status(item)
    except (DatabaseError, ProcrastinateException) as e:
        log.error("Demo WhatsApp update not saved: %s", type(e).__name__)
        return HttpResponse(status=503)
    return HttpResponse(status=200)
