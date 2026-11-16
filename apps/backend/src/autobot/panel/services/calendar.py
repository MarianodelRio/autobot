"""The platform's single Google service account (D1): its own email, so a client
can share their calendar with it. Never its private key."""

from django.conf import settings
from ninja import Schema

from integrations.google_calendar.client import service_account_email


class ServiceAccountOut(Schema):
    configured: bool
    email: str | None


def service_account() -> ServiceAccountOut:
    configured = bool(settings.GOOGLE_SERVICE_ACCOUNT_FILE)
    email = service_account_email(settings.GOOGLE_SERVICE_ACCOUNT_FILE) if configured else None
    return ServiceAccountOut(configured=configured, email=email)
