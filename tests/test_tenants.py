"""CI gate (design.md §17.3): every tenants/*/tenant.yaml in the repository is valid with
the registered packs. CI has no secrets.yaml, so only disabled main channels are allowed."""

from django.conf import settings

from flowpilot.tenancy.registry import load_registry
from packs.registry import PACKS


def test_every_tenant_in_the_repository_is_valid() -> None:
    registry = load_registry(settings.TENANTS_DIR, None, PACKS)
    assert registry.problems == {}
