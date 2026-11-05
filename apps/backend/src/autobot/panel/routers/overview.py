"""`GET overview`: the Resumen screen's one call."""

from django.http import HttpRequest
from ninja import Router

from autobot.panel.services.overview import Overview, build_overview

router = Router(tags=["overview"])


@router.get("/overview", response=Overview)
def overview(request: HttpRequest) -> Overview:
    return build_overview()
