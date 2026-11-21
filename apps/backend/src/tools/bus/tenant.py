"""Shared paths for local, ignored bus dataset exports."""

import re
import sys
from pathlib import Path

from tools._paths import REPO_ROOT

_SLUG_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")


class TenantDesconocido(Exception):
    """The slug is malformed or the tenant has no timetable dataset."""


def dataset_path(slug: str) -> Path:
    """The working timetable folder relative to the repository root."""
    if len(slug) > 64 or not _SLUG_RE.fullmatch(slug):
        raise TenantDesconocido(f"slug de tenant inválido: '{slug}'")
    return Path("var") / "datos" / slug / "timetable"


def dataset_dir(slug: str, repo_root: Path = REPO_ROOT) -> Path:
    path = repo_root / dataset_path(slug)
    if not path.is_dir():
        raise TenantDesconocido(f"el tenant '{slug}' no tiene dataset de horarios en {path}")
    return path


def published_dir(slug: str, repo_root: Path = REPO_ROOT) -> Path:
    dataset_path(slug)
    return repo_root / "var" / "datos" / slug / ".publicado" / "timetable"


def dataset_from_argv(
    argv: list[str] | None, usage: str, repo_root: Path = REPO_ROOT
) -> Path | int:
    """The dataset folder named by the single NOMBRE argument of a bus tool.

    On a wrong command line or an unknown tenant it prints the problem and returns
    the exit code (2) instead, so `main` can `return` it unchanged."""
    args = argv if argv is not None else sys.argv[1:]
    if len(args) != 1:
        print(usage)
        return 2
    try:
        return dataset_dir(args[0], repo_root)
    except TenantDesconocido as exc:
        print(f"✗ {exc}")
        return 2
