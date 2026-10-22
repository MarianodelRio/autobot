"""Root URLs.

Public routes are the only ones Caddy forwards (design.md §13, §14.3): the webhooks and
/health. The Admin is mounted apart: Caddy never routes it, and the operator reaches it
through the SSH tunnel to 127.0.0.1:8000.
"""

from django.contrib import admin
from django.urls import URLPattern, URLResolver, path

from flowpilot.channels import views as webhooks
from flowpilot.channels.test_bot.views import telegram_test
from flowpilot.ops.views import health

public: list[URLPattern | URLResolver] = [
    path("webhooks/whatsapp/<str:public_id>", webhooks.whatsapp, name="webhook-whatsapp"),
    path("webhooks/telegram/<str:public_id>", webhooks.telegram, name="webhook-telegram"),
    path("webhooks/telegram-test", telegram_test, name="webhook-telegram-test"),
    path("health", health, name="health"),
]

internal: list[URLPattern | URLResolver] = [
    path("admin/", admin.site.urls),
]

urlpatterns = public + internal
