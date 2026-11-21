"""Paths shared by the repository tools."""

from pathlib import Path

_HERE = Path(__file__).resolve()

# src/tools/_paths.py -> tools -> src -> backend -> apps -> repository root. Inside the
# backend image the code lives at /app/src, with no repository above it: the tools that
# use REPO_ROOT only run from a checkout, but modules that the web app imports (e.g.
# `tools.ops.qr`) import this one too, so it must not fail there. Fall back to the
# image's project root (/app).
REPO_ROOT = _HERE.parents[4] if len(_HERE.parents) > 4 else _HERE.parents[2]
