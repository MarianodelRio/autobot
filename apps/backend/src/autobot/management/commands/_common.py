"""Helpers shared by the management commands. The leading underscore keeps Django from
treating this module as a command."""

from django.core.management.base import CommandError

from autobot.tenancy.registry import LoadedTenant, get_registry


def registry_tenant(slug: str) -> LoadedTenant:
    """The loaded tenant with this slug, or a `CommandError`."""
    tenant = get_registry().by_slug.get(slug)
    if tenant is None:
        raise CommandError("Negocio desconocido.")
    return tenant
