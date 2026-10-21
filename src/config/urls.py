"""Root URLs. Webhooks, /health and the separately mounted Admin arrive with T-3.3."""

from django.urls import URLPattern, URLResolver

urlpatterns: list[URLPattern | URLResolver] = []
