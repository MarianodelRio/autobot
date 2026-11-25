"""Helpers shared by the panel's services."""

from autobot.panel.errors import ApiError
from autobot.tenancy.registry import LoadedTenant, get_registry


def get_tenant_or_404(slug: str) -> LoadedTenant:
    # Every panel request starts with a fresh check that pins its snapshot
    # (`PanelFreshConfigMiddleware`), so this never reads another worker's old one.
    tenant = get_registry().by_slug.get(slug)
    if tenant is None:
        raise ApiError("not_found", "No se encuentra el negocio", 404)
    return tenant
