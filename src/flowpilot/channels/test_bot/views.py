"""`POST /webhooks/telegram-test`: the test bot's webhook.

Same checks as a tenant's webhook (IP limit, size, secret token before parsing, JSON),
but it does not know the tenant yet: it only writes `test_bot_event`, which has no RLS.
Off (404) without TEST_BOT_WEBHOOK_SECRET: local development uses `telegram_poll`.
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
from flowpilot.channels.adapters import TELEGRAM, test_bot_secrets
from flowpilot.channels.ratelimit import client_ip
from flowpilot.channels.test_bot.selector import store_update
from flowpilot.ops.logging import bind

log = logging.getLogger(__name__)


@csrf_exempt
@require_POST
def telegram_test(request: HttpRequest) -> HttpResponse:
    bind(channel="test")
    ip = client_ip(request)
    if webhooks.limiter.blocked(ip):
        return HttpResponse(status=429)
    secrets = test_bot_secrets()
    if not settings.TEST_BOT_WEBHOOK_SECRET or secrets is None:
        return HttpResponse(status=404)
    try:
        declared = int(request.META.get("CONTENT_LENGTH") or 0)
    except ValueError:
        return HttpResponse(status=400)
    if declared > webhooks.MAX_BODY or len(request.body) > webhooks.MAX_BODY:
        return HttpResponse(status=400)
    if not TELEGRAM.verify(request, None, secrets):
        webhooks.limiter.record(ip)
        log.warning("Invalid test bot webhook secret")
        return HttpResponse(status=401)
    try:
        body = json.loads(request.body)
    except ValueError:
        return HttpResponse(status=400)
    if not isinstance(body, dict):
        return HttpResponse(status=400)
    try:
        store_update(body)
    except (DatabaseError, ProcrastinateException) as e:
        log.error("Test bot update not saved: %s", type(e).__name__)
        return HttpResponse(status=503)
    return HttpResponse(status=200)
