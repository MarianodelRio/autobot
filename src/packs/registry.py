"""Explicit pack registry (design.md §8.1): the only module that imports the packs, and
the only way the platform reaches them. Packs are added here as they are ported (T-4.4,
T-5.x); tests register the toy pack themselves."""

from core.pack import Pack

PACKS: dict[str, Pack] = {}
