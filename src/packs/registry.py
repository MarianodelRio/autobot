"""Explicit pack registry (design.md §8.1): the only module that imports the packs.

The packs and their type arrive with T-2.4; the module exists now as the single entry
point allowed by the import-linter contracts (T-0.4).
"""

PACKS: dict[str, object] = {}
