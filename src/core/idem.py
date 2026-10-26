from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class IdemKeys:
    """Idempotency keys.

    `event(name)` is bound to the inbound event being processed, so reprocessing it
    yields the same key. `stable(name)` identifies an entity across runs (sweeps), e.g.
    `stable("reminder:<gcal_id>:<start>")`.
    """

    event_id: UUID | None

    def event(self, name: str) -> str:
        if self.event_id is None:
            raise RuntimeError("IdemKeys.event() needs an inbound event; use stable()")
        return f"{name}:{self.event_id}"

    def stable(self, name: str) -> str:
        return name
