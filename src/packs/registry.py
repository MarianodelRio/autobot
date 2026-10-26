"""Explicit pack registry: the only module that imports the packs, and
the only way the platform reaches them. Packs are added here as they are written;
tests register the toy pack themselves."""

from core.pack import Pack
from packs.bus import pack as bus
from packs.salon import pack as salon

PACKS: dict[str, Pack] = {p.name: p for p in (bus.pack, salon.pack)}
