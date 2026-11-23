"""Circuit breaker per messaging provider (WhatsApp, Telegram) of one outbound worker.

When a provider is down, every send would fail, one by one, taking its slot of the pool
for a timeout. The breaker opens after `THRESHOLD` consecutive transport failures (5xx,
network, timeout; never a 4xx or an auth refusal) that come from at least `MIN_TENANTS`
different tenants, so one misconfigured business cannot cut the others off. While open,
`send_message` does not call the provider: it defers the message (`RetryLater`) and, at
most once per `PROBE_EVERY_S`, one caller runs a read-only probe; its success closes the
breaker.

In memory and per process (ADR-024): it needs no coordination, and a restarted worker
starts closed and learns again in a handful of sends. Thread-safe. Opening and closing
are reported through `on_change`, which writes the signal `ops_check` turns into the one
`provider_outage` alert.
"""

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from uuid import UUID

THRESHOLD = 5
MIN_TENANTS = 2
PROBE_EVERY_S = 60.0


@dataclass
class _Provider:
    failures: int = 0
    tenants: set[UUID] = field(default_factory=set)
    open_since: float | None = None
    next_probe_at: float = 0.0


class ProviderBreaker:
    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.monotonic,
        on_change: Callable[[str, bool], None] | None = None,
    ) -> None:
        self._clock = clock
        self._on_change = on_change
        self._lock = threading.Lock()
        self._providers: dict[str, _Provider] = {}

    def _get(self, provider: str) -> _Provider:
        return self._providers.setdefault(provider, _Provider())

    def is_open(self, provider: str) -> bool:
        with self._lock:
            return self._get(provider).open_since is not None

    def record_success(self, provider: str) -> None:
        """The provider answered (anything but a transport failure): count restarts, and
        an open breaker closes."""
        with self._lock:
            state = self._get(provider)
            was_open = state.open_since is not None
            self._providers[provider] = _Provider()
        if was_open:
            self._notify(provider, False)

    def record_failure(self, provider: str, tenant_id: UUID) -> None:
        with self._lock:
            state = self._get(provider)
            state.failures += 1
            state.tenants.add(tenant_id)
            opened = (
                state.open_since is None
                and state.failures >= THRESHOLD
                and len(state.tenants) >= MIN_TENANTS
            )
            if opened:
                state.open_since = self._clock()
                state.next_probe_at = state.open_since + PROBE_EVERY_S
        if opened:
            self._notify(provider, True)

    def claim_probe(self, provider: str) -> bool:
        """True for one caller per `PROBE_EVERY_S` while the breaker is open."""
        with self._lock:
            state = self._get(provider)
            now = self._clock()
            if state.open_since is None or now < state.next_probe_at:
                return False
            state.next_probe_at = now + PROBE_EVERY_S
            return True

    def probe_result(self, provider: str, ok: bool) -> None:
        if ok:
            self.record_success(provider)
        else:  # still down: tell ops it is, so the signal does not look stale
            self._notify(provider, True)

    def seconds_to_probe(self, provider: str) -> float:
        with self._lock:
            return max(0.0, self._get(provider).next_probe_at - self._clock())

    def reset(self) -> None:
        with self._lock:
            self._providers.clear()

    def _notify(self, provider: str, is_open: bool) -> None:
        if self._on_change is not None:
            self._on_change(provider, is_open)
