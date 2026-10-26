"""`POST /webhooks/telegram-demo`: the demo bot's Telegram door webhook.

Same checks as a tenant's webhook (IP limit, size, secret token before parsing, JSON),
but it does not know the tenant yet: it only writes `demo_event`, which has no RLS.
Off (404) without a token or a webhook secret: local development uses `telegram_poll`.
"""

import json
import logging

from django.conf import settings
from django.db import Error as DatabaseError
from django.http import HttpRequest, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from procrastinate.exceptions import ProcrastinateException

from flowpilot.channels import views as webhooks
from flowpilot.channels.adapters import TELEGRAM
from flowpilot.channels.base import InboundItem
from flowpilot.channels.demo.doors import door
from flowpilot.channels.demo.selector import store_event
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
