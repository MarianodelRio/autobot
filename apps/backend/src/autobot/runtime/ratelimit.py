"""Outgoing rate limiter: a global rate plus a minimum interval per recipient.

Used by the owner-notice bot (Telegram answers 429 above ~30 messages/s per bot and
~1 message/s per chat). "Next free slot" scheme: every grant reserves the next instant at
which the bot, and that recipient, may be used again. A caller that would have to wait
more than `max_wait_s` is NOT granted anything: it gets the wait and defers its job
(`SendRetry`), so no worker thread sleeps long; a shorter wait is slept here, with no lock
held.

IN MEMORY AND PER PROCESS. It is valid while there is ONE outbound worker process (the
current deployment, ADR-005/ADR-024): two processes would each allow the full rate. A
limiter shared through the database or Redis is future work
(`docs/arquitectura/capacidad-y-crecimiento.md`). Thread-safe.
"""

import threading
import time
from collections.abc import Callable

MAX_KEYS = 10_000  # bound on memory: past it, the slots already in the past are forgotten


class SlotLimiter:
    def __init__(
        self,
        *,
        rate_per_s: float,
        key_interval_s: float,
        max_wait_s: float = 1.0,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._gap_s = 1.0 / rate_per_s
        self._key_interval_s = key_interval_s
        self._max_wait_s = max_wait_s
        self._clock = clock
        self._sleep = sleep
        self._lock = threading.Lock()
        self._next_global = 0.0
        self._next_by_key: dict[str, float] = {}

    def acquire(self, key: str) -> float | None:
        """Take a slot for `key`. Returns None when it was granted (after sleeping at most
        `max_wait_s`), or the seconds to wait before trying again when no slot is free
        soon enough (nothing was reserved: the caller must not send)."""
        with self._lock:
            now = self._clock()
            slot = max(now, self._next_global, self._next_by_key.get(key, 0.0))
            wait = slot - now
            if wait > self._max_wait_s:
                return wait
            self._next_global = slot + self._gap_s
            self._next_by_key[key] = slot + self._key_interval_s
            if len(self._next_by_key) > MAX_KEYS:
                self._next_by_key = {k: t for k, t in self._next_by_key.items() if t > now}
        if wait > 0:
            self._sleep(wait)
        return None
