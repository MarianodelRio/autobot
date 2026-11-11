"""Root URLs.

Public routes are the only ones Caddy forwards: the webhooks and /health (its
`@public` matcher in deploy/caddy/Caddyfile is the actual enforcement). /health/internal
is deliberately not in that matcher nor in `public` below: it only answers on the
docker network or 127.0.0.1, which is all `deploy.sh` needs. The panel's API is mounted
apart (`PanelGateMiddleware`), reached only through the SSH tunnel.
"""

from django.urls import URLPattern, URLResolver, path

from autobot.channels import views as webhooks
from autobot.channels.demo.views import telegram_demo, whatsapp_demo
from autobot.ops.views import health, health_internal
from autobot.owner.views import telegram_notify
from autobot.panel.api import api

public: list[URLPattern | URLResolver] = [
    path("webhooks/whatsapp/<str:public_id>", webhooks.whatsapp, name="webhook-whatsapp"),
    path("webhooks/telegram/<str:public_id>", webhooks.telegram, name="webhook-telegram"),
    path("webhooks/telegram-demo", telegram_demo, name="webhook-telegram-demo"),
    path("webhooks/whatsapp-demo", whatsapp_demo, name="webhook-whatsapp-demo"),
    path("webhooks/telegram-notify", telegram_notify, name="webhook-telegram-notify"),
    path("health", health, name="health"),
]

urlpatterns = (
    public
    + [path("health/internal", health_internal, name="health-internal")]
    + [path("api/panel/", api.urls)]
)
