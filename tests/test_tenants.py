"""CI gate: every pack template validates, including its initial datasets."""

import shutil
from pathlib import Path

import pytest
import yaml

from autobot.tenancy.registry import load_registry
from core.pack import Pack
from packs.registry import PACKS


@pytest.mark.parametrize("pack", list(PACKS.values()), ids=list(PACKS))
def test_every_pack_template_is_valid(pack: Pack, tmp_path: Path) -> None:
    assert pack.template is not None
    document = yaml.safe_load((pack.template / "document.yaml").read_text())
    target = tmp_path / document["slug"]
    shutil.copytree(pack.template, target)
    (target / "document.yaml").rename(target / "tenant.yaml")
    registry = load_registry(tmp_path, None, PACKS)
    assert registry.problems == {}
    (tenant,) = registry.tenants
    assert tenant.is_demo
    assert tenant.id.version == 7
    assert not tenant.main_enabled
    assert set(pack.template_blank) <= set(pack.config_schema.model_fields)
