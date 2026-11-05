"""CI gate: every pack template validates, including its initial datasets."""

import pytest

from autobot.tenancy.registry import load_registry, source_from_dir
from core.pack import Pack
from packs.registry import PACKS


@pytest.mark.parametrize("pack", list(PACKS.values()), ids=list(PACKS))
def test_every_pack_template_is_valid(pack: Pack) -> None:
    assert pack.template is not None
    registry = load_registry([source_from_dir(pack.template)], PACKS)
    assert registry.problems == {}
    (tenant,) = registry.tenants
    assert tenant.is_demo
    assert tenant.id.version == 7
    assert not tenant.main_enabled
    assert set(pack.template_blank) <= set(pack.config_schema.model_fields)
