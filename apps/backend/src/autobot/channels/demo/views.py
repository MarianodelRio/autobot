"""`POST /webhooks/telegram-demo` and `GET|POST /webhooks/whatsapp-demo`: the demo
bot's door webhooks.

Same checks as a tenant's webhook (size, signature/secret before parsing, JSON, the
invalid-signature limit per IP and door), but neither knows the tenant yet: they only
write `demo_event`, which has no RLS. Off (404) without the door's credentials: local
development uses `telegram_poll` for Telegram; the WhatsApp door only runs on the server
(a Meta number has one webhook URL).
"""

import logging

from django.conf import settings
from django.db import Error as DatabaseError
from django.http import HttpRequest, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods, require_POST
from procrastinate.exceptions import ProcrastinateException

from autobot.channels import views as webhooks
from autobot.channels.adapters import TELEGRAM, WHATSAPP
from autobot.channels.base import InboundItem, StatusItem
from autobot.channels.demo.doors import door
from autobot.channels.demo.selector import route_demo_status, store_event
from autobot.ops.logging import bind
from autobot.runtime.models import Channel

log = logging.getLogger(__name__)


@csrf_exempt
@require_POST
def telegram_demo(request: HttpRequest) -> HttpResponse:
    bind(channel=str(Channel.DEMO_TG))
    door_ = door(Channel.DEMO_TG)
    if not settings.DEMO_TELEGRAM_WEBHOOK_SECRET or door_ is None:
        return HttpResponse(status=404)
    if webhooks.body_too_large(request):
        return HttpResponse(status=400)
    if not TELEGRAM.verify(request, None, door_.secrets):
        log.warning("Invalid demo Telegram webhook secret")
        return webhooks.reject_unauthenticated(request, "telegram-demo")
    body = webhooks.json_object(request)
    if body is None:
        return HttpResponse(status=400)
    try:
        for item in TELEGRAM.parse(body, None):
            if isinstance(item, InboundItem):
                store_event(door_, item)
    except (DatabaseError, ProcrastinateException) as e:
        return webhooks.storage_failure(e, "Demo Telegram update")
    return HttpResponse(status=200)


@csrf_exempt
@require_http_methods(["GET", "POST"])
def whatsapp_demo(request: HttpRequest) -> HttpResponse:
    bind(channel=str(Channel.DEMO_WA))
    door_ = door(Channel.DEMO_WA)
    if door_ is None:
        return HttpResponse(status=404)
    if request.method == "GET":  # Meta's subscription handshake
        challenge = WHATSAPP.verify_subscription(request.GET.dict(), door_.secrets)
        if challenge is None:
            log.warning("Demo WhatsApp verification refused")
            response = webhooks.reject_unauthenticated(request, "whatsapp-demo")
            return HttpResponse(status=403) if response.status_code == 401 else response
        return HttpResponse(challenge, content_type="text/plain")
    if webhooks.body_too_large(request):
        return HttpResponse(status=400)
    if not WHATSAPP.verify(request, door_.description, door_.secrets):
        log.warning("Invalid demo WhatsApp webhook signature")
        return webhooks.reject_unauthenticated(request, "whatsapp-demo")
    body = webhooks.json_object(request)
    if body is None:
        return HttpResponse(status=400)
    try:
        for item in WHATSAPP.parse(body, door_.description):
            if isinstance(item, InboundItem):
                store_event(door_, item)
            elif isinstance(item, StatusItem):
                route_demo_status(item)
    except (DatabaseError, ProcrastinateException) as e:
        return webhooks.storage_failure(e, "Demo WhatsApp update")
    return HttpResponse(status=200)
