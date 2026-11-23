"""A fake `os.statvfs` for the ops disk and inode readings."""

import os
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any

import pytest


def statvfs_for(used_pct: float = 1, inodes_pct: float = 1) -> Callable[[str], Any]:
    """A statvfs of a 1000-block, 1000-inode filesystem `used_pct`/`inodes_pct` full."""
    return lambda _path: SimpleNamespace(
        f_blocks=1000,
        f_bavail=round(1000 * (100 - used_pct) / 100),
        f_files=1000,
        f_favail=round(1000 * (100 - inodes_pct) / 100),
    )


def fake_disk(monkeypatch: pytest.MonkeyPatch, used_pct: float = 1, inodes_pct: float = 1) -> None:
    monkeypatch.setattr(os, "statvfs", statvfs_for(used_pct, inodes_pct))
