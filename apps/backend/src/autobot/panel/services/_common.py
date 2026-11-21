"""Helpers shared by the panel's services."""

from autobot.panel.errors import ApiError
from autobot.tenancy.registry import LoadedTenant, get_registry


def get_tenant_or_404(slug: str) -> LoadedTenant:
    tenant = get_registry().by_slug.get(slug)
    if tenant is None:
        # This process's own registry may be up to 2 s behind a write made by
        # another gunicorn worker (just created or renamed): force a fresh check
        # before giving up.
        tenant = get_registry(force=True).by_slug.get(slug)
    if tenant is None:
        raise ApiError("not_found", "No se encuentra el negocio", 404)
    return tenant
