"""`deploy.yml` is the only workflow holding the server's SSH key: its actions must be
pinned by commit SHA, not a mutable tag, so a compromised action can't reach it."""

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[4]
SHA_PIN = re.compile(r"^[^@]+@[0-9a-f]{40}$")


def test_every_action_is_pinned_by_sha() -> None:
    workflow = yaml.safe_load((ROOT / ".github/workflows/deploy.yml").read_text())
    uses = [
        step["uses"] for job in workflow["jobs"].values() for step in job["steps"] if "uses" in step
    ]
    assert uses, "no actions found: did the workflow change shape?"
    for use in uses:
        assert SHA_PIN.match(use), f"{use} is not pinned by a 40-character SHA"
