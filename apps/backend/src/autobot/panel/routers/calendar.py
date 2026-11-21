"""`GET /calendar/service-account`."""

from django.http import HttpRequest
from ninja import Router

from autobot.panel.services import calendar as service
from autobot.panel.services.calendar import ServiceAccountOut

router = Router(tags=["calendar"])


@router.get("/calendar/service-account", response=ServiceAccountOut)
def service_account(request: HttpRequest) -> ServiceAccountOut:
    return service.service_account()
