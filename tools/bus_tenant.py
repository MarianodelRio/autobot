"""Shared by the bus timetable tools (design.md §10.1, §16.3): where a tenant's dataset
lives and how its published versions are tagged. Tools run on a developer machine with
the repository checked out; they never touch the server."""

import re
from pathlib import Path

from packs.bus.pack import DATASET_DIR

REPO_ROOT = Path(__file__).resolve().parent.parent
_SLUG_RE = re.compile(r"[a-z0-9][a-z0-9-]*")


class TenantDesconocido(Exception):
    """The slug is malformed or the tenant has no timetable dataset."""


def dataset_path(slug: str) -> Path:
    """The dataset folder relative to the repository root (for `git archive`)."""
    if not _SLUG_RE.fullmatch(slug):
        raise TenantDesconocido(f"slug de tenant inválido: '{slug}'")
    return Path("tenants") / slug / DATASET_DIR


def dataset_dir(slug: str, repo_root: Path = REPO_ROOT) -> Path:
    path = repo_root / dataset_path(slug)
    if not path.is_dir():
        raise TenantDesconocido(f"el tenant '{slug}' no tiene dataset de horarios en {path}")
    return path


def tag_prefix(slug: str) -> str:
    """Published versions are tagged `datos/<slug>/AAAA-MM-DD` (§10.1)."""
    return f"datos/{slug}/"
