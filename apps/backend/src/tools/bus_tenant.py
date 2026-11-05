"""Shared paths for local, ignored bus dataset exports."""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent
_SLUG_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")


class TenantDesconocido(Exception):
    """The slug is malformed or the tenant has no timetable dataset."""


def dataset_path(slug: str) -> Path:
    """The working timetable folder relative to the repository root."""
    if len(slug) > 64 or not _SLUG_RE.fullmatch(slug):
        raise TenantDesconocido(f"slug de tenant inválido: '{slug}'")
    return Path("datos") / slug / "timetable"


def dataset_dir(slug: str, repo_root: Path = REPO_ROOT) -> Path:
    path = repo_root / dataset_path(slug)
    if not path.is_dir():
        raise TenantDesconocido(f"el tenant '{slug}' no tiene dataset de horarios en {path}")
    return path


def published_dir(slug: str, repo_root: Path = REPO_ROOT) -> Path:
    dataset_path(slug)
    return repo_root / "datos" / slug / ".publicado" / "timetable"
