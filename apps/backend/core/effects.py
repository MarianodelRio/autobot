"""A generic, scoped journal for authorization checked before an external effect."""

from typing import Any, Protocol


class EffectJournal(Protocol):
    def get(self, key: str) -> dict[str, Any] | None: ...
    def put(self, key: str, value: dict[str, Any]) -> None: ...
