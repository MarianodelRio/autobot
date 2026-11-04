"""In-memory effects survive replay, as the separately committed runtime journal does."""

import copy
from typing import Any

from core.errors import PermanentError


class MemoryEffects:
    def __init__(self, storage: dict[str, dict[str, Any]], scope: str) -> None:
        self.storage, self.scope = storage, scope

    def get(self, key: str) -> dict[str, Any] | None:
        value = self.storage.get(f"{self.scope}:{key}")
        return copy.deepcopy(value) if value is not None else None

    def put(self, key: str, value: dict[str, Any]) -> None:
        scoped = f"{self.scope}:{key}"
        if scoped in self.storage and self.storage[scoped] != value:
            raise PermanentError("Conflicting effect authorization")
        self.storage[scoped] = copy.deepcopy(value)
