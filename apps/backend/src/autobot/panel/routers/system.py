"""Live system state and retained operational history."""

from django.http import HttpRequest
from ninja import Router

from autobot.panel.services.system import SystemOut, build_system

router = Router(tags=["system"])


@router.get("/system", response=SystemOut)
def system(request: HttpRequest) -> SystemOut:
    return build_system()
