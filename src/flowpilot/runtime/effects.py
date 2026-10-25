"""Short RLS transactions around effect evidence; never around the external call."""

import copy
import hashlib
from typing import Any
from uuid import UUID

from core.errors import PermanentError
from flowpilot.runtime.models import InboundEvent
from flowpilot.tenancy.tx import tenant_tx


class StoredEffects:
    def __init__(
        self,
        tenant_id: UUID,
        event_id: UUID,
        contact_id: UUID,
        channel: str,
        calendar_id: str | None,
    ) -> None:
        self.tenant_id, self.event_id, self.channel = tenant_id, event_id, channel
        self.scope = hashlib.sha256(
            f"{tenant_id}:{event_id}:{contact_id}:{channel}:{calendar_id or '-'}".encode()
        ).hexdigest()

    def _event(self, *, lock: bool = False) -> InboundEvent:
        query = InboundEvent.objects.select_for_update() if lock else InboundEvent.objects
        event = query.get(id=self.event_id)
        if event.status != InboundEvent.Status.PENDING or event.channel != self.channel:
            raise PermanentError("Effect journal is no longer writable")
        return event

    def get(self, key: str) -> dict[str, Any] | None:
        with tenant_tx(self.tenant_id):
            value = self._event().effect_state.get(f"{self.scope}:{key}")
            return copy.deepcopy(value) if isinstance(value, dict) else None

    def put(self, key: str, value: dict[str, Any]) -> None:
        with tenant_tx(self.tenant_id):
            event = self._event(lock=True)
            scoped = f"{self.scope}:{key}"
            previous = event.effect_state.get(scoped)
            if previous is not None and previous != value:
                raise PermanentError("Conflicting effect authorization")
            if previous is None:
                event.effect_state[scoped] = copy.deepcopy(value)
                event.save(update_fields=["effect_state"])
