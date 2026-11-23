"""`POST /webhooks/telegram-notify`: the owner bot's webhook
(ADR-007). Same checks as `telegram_demo`, in the
same order (the invalid-secret limit is per IP and bot); it only writes `owner_event`,
which has no RLS, so the tenant need not be known yet."""

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
from autobot.ops.logging import bind
from autobot.owner.inbox import store_owner_event
from autobot.runtime.notifications import bot_secrets

log = logging.getLogger(__name__)


@csrf_exempt
@require_POST
def telegram_notify(request: HttpRequest) -> HttpResponse:
    bind(channel="owner")
    secrets = bot_secrets()
    if not settings.NOTIFY_BOT_WEBHOOK_SECRET or secrets is None:
        return HttpResponse(status=404)
    if webhooks.body_too_large(request):
        return HttpResponse(status=400)
    if not TELEGRAM.verify(request, None, secrets):
        if not webhooks.limiter.blocked(webhooks.limiter_key(request, "telegram-notify")):
            log.warning("Invalid owner bot webhook secret")
        return webhooks.reject_unauthenticated(request, "telegram-notify")
    body = webhooks.json_object(request)
    if body is None:
        return HttpResponse(status=400)
    try:
        with webhooks.webhook_db_limits():
            for item in TELEGRAM.parse(body, None):
                if isinstance(item, InboundItem):
                    store_owner_event(item)
    except (DatabaseError, ProcrastinateException) as e:
        return webhooks.storage_failure(e, "Owner bot update")
    return HttpResponse(status=200)
