"""`POST /webhooks/telegram-demo` and `GET|POST /webhooks/whatsapp-demo`: the demo
bot's door webhooks.

Same checks as a tenant's webhook (size, signature/secret before parsing, JSON, the
invalid-signature limit per IP and door), but neither knows the tenant yet: they only
write `demo_event`, which has no RLS. Off (404) without the door's credentials: local
development uses `telegram_poll` for Telegram; the WhatsApp door only runs on the server
(a Meta number has one webhook URL).
"""

from typing import Any

from django.conf import settings
from django.http import HttpRequest, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods, require_POST

from autobot.channels import views as webhooks
from autobot.channels.adapters import TELEGRAM, WHATSAPP
from autobot.channels.base import InboundItem, StatusItem
from autobot.channels.demo.doors import door
from autobot.channels.demo.selector import route_demo_status, store_event
from autobot.ops.logging import bind
from autobot.runtime.models import Channel


@csrf_exempt
@require_POST
def telegram_demo(request: HttpRequest) -> HttpResponse:
    bind(channel=str(Channel.DEMO_TG))
    door_ = door(Channel.DEMO_TG)
    if not settings.DEMO_TELEGRAM_WEBHOOK_SECRET or door_ is None:
        return HttpResponse(status=404)

    def handle(body: dict[str, Any]) -> None:
        for item in TELEGRAM.parse(body, None):
            if isinstance(item, InboundItem):
                store_event(door_, item)

    return webhooks.receive(
        request,
        route="telegram-demo",
        who="demo Telegram",
        verify=lambda: TELEGRAM.verify(request, None, door_.secrets),
        handle=handle,
    )


@csrf_exempt
@require_http_methods(["GET", "POST"])
def whatsapp_demo(request: HttpRequest) -> HttpResponse:
    bind(channel=str(Channel.DEMO_WA))
    door_ = door(Channel.DEMO_WA)
    if door_ is None:
        return HttpResponse(status=404)
    route = "whatsapp-demo"
    if request.method == "GET":
        return webhooks.handle_meta_handshake(request, door_.secrets, route=route, who="demo door")

    def handle(body: dict[str, Any]) -> None:
        for item in WHATSAPP.parse(body, door_.description):
            if isinstance(item, InboundItem):
                store_event(door_, item)
            elif isinstance(item, StatusItem):
                route_demo_status(item)

    return webhooks.receive(
        request,
        route=route,
        who="demo WhatsApp",
        verify=lambda: WHATSAPP.verify(request, door_.description, door_.secrets),
        handle=handle,
    )
