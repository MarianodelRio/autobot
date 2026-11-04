"""The panel's NinjaAPI (DESIGN §6.1, §6.3): mounts routers and shapes every error as
`{"code", "message", "details"}`, except auth/CSRF failures, which keep django-ninja's
own `{"detail": ...}` shape (DESIGN doesn't ask otherwise, and the frontend only needs
the status code there)."""

from django.http import Http404, HttpRequest, HttpResponse
from ninja import NinjaAPI
from ninja.errors import ValidationError as NinjaValidationError

from autobot.panel.auth import PanelAuth
from autobot.panel.auth import router as auth_router
from autobot.panel.errors import CODE_STATUS, ApiError
from autobot.panel.routers.activity import router as activity_router
from autobot.panel.routers.audit import router as audit_router
from autobot.panel.routers.contacts import router as contacts_router
from autobot.panel.routers.incidents import router as incidents_router
from autobot.panel.routers.logs import router as logs_router
from autobot.panel.routers.overview import router as overview_router
from autobot.panel.routers.packs import router as packs_router
from autobot.panel.routers.system import router as system_router
from autobot.panel.routers.tenants import router as tenants_router
from autobot.tenancy.store import StoreError

api = NinjaAPI(
    title="Autobot panel", version="1", urls_namespace="panel", auth=PanelAuth(), docs_url=None
)
api.add_router("/auth", auth_router)
api.add_router("", system_router)
api.add_router("", logs_router)
api.add_router("", audit_router)
api.add_router("", incidents_router)
api.add_router("", activity_router)
api.add_router("", contacts_router)
api.add_router("", overview_router)
api.add_router("", packs_router)
api.add_router("", tenants_router)


@api.exception_handler(ApiError)
def _api_error(request: HttpRequest, exc: ApiError) -> HttpResponse:
    return api.create_response(
        request,
        {"code": exc.code, "message": exc.message, "details": exc.details},
        status=exc.status,
    )


@api.exception_handler(StoreError)
def _store_error(request: HttpRequest, exc: StoreError) -> HttpResponse:
    return api.create_response(
        request,
        {"code": exc.code, "message": exc.message, "details": exc.details},
        status=CODE_STATUS.get(exc.code, 400),
    )


@api.exception_handler(NinjaValidationError)
def _validation_error(request: HttpRequest, exc: NinjaValidationError) -> HttpResponse:
    details = [
        f"{'.'.join(str(part) for part in item['loc'])}: {item['msg']}" for item in exc.errors
    ]
    return api.create_response(
        request,
        {"code": "validation_error", "message": "Entrada no válida.", "details": details},
        status=422,
    )


@api.exception_handler(Http404)
def _not_found(request: HttpRequest, exc: Http404) -> HttpResponse:
    return api.create_response(
        request, {"code": "not_found", "message": "No encontrado.", "details": []}, status=404
    )
