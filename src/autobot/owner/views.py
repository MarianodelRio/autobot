"""`POST /webhooks/telegram-notify`: the owner bot's webhook
(ADR-007). Same checks as `telegram_demo`, in the
same order; it only writes `owner_event`, which has no RLS, so the tenant need not be
known yet."""

import json
import logging

from django.conf import settings
from django.db import Error as DatabaseError
from django.http import HttpRequest, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from procrastinate.exceptions import ProcrastinateException

from autobot.channels import views as webhooks
from autobot.channels.adapters import TELEGRAM
from autobot.channels.base import InboundItem
from autobot.channels.ratelimit import client_ip
from autobot.ops.logging import bind
from autobot.owner.inbox import store_owner_event
from autobot.runtime.notifications import bot_secrets

log = logging.getLogger(__name__)


@csrf_exempt
@require_POST
def telegram_notify(request: HttpRequest) -> HttpResponse:
    bind(channel="owner")
    ip = client_ip(request)
    if webhooks.limiter.blocked(ip):
        return HttpResponse(status=429)
    secrets = bot_secrets()
    if not settings.NOTIFY_BOT_WEBHOOK_SECRET or secrets is None:
        return HttpResponse(status=404)
    try:
        declared = int(request.META.get("CONTENT_LENGTH") or 0)
    except ValueError:
        return HttpResponse(status=400)
    if declared > webhooks.MAX_BODY or len(request.body) > webhooks.MAX_BODY:
        return HttpResponse(status=400)
    if not TELEGRAM.verify(request, None, secrets):
        webhooks.limiter.record(ip)
        log.warning("Invalid owner bot webhook secret")
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
                store_owner_event(item)
    except (DatabaseError, ProcrastinateException) as e:
        log.error("Owner bot update not saved: %s", type(e).__name__)
        return HttpResponse(status=503)
    return HttpResponse(status=200)
