"""Paths shared by the repository tools."""

from pathlib import Path

# src/tools/_paths.py -> tools -> src -> backend -> apps -> repository root.
REPO_ROOT = Path(__file__).resolve().parents[4]
