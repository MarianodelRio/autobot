"""Root URLs.

Public routes are the only ones Caddy forwards: the webhooks and
/health. The Admin is mounted apart: Caddy never routes it, and the operator reaches it
through the SSH tunnel to 127.0.0.1:8000.
"""

from django.urls import URLPattern, URLResolver, path

from autobot.admin import site
from autobot.channels import views as webhooks
from autobot.channels.demo.views import telegram_demo, whatsapp_demo
from autobot.ops.views import health
from autobot.owner.views import telegram_notify

public: list[URLPattern | URLResolver] = [
    path("webhooks/whatsapp/<str:public_id>", webhooks.whatsapp, name="webhook-whatsapp"),
    path("webhooks/telegram/<str:public_id>", webhooks.telegram, name="webhook-telegram"),
    path("webhooks/telegram-demo", telegram_demo, name="webhook-telegram-demo"),
    path("webhooks/whatsapp-demo", whatsapp_demo, name="webhook-whatsapp-demo"),
    path("webhooks/telegram-notify", telegram_notify, name="webhook-telegram-notify"),
    path("health", health, name="health"),
]

internal: list[URLPattern | URLResolver] = [
    path("admin/", site.urls),
]

urlpatterns = public + internal
