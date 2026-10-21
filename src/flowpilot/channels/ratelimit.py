"""Sliding-window limits kept in memory, per process (design.md §13, §7.2):

- per IP, of webhook requests with an invalid signature (each `web` worker counts on its
  own; valid requests are never counted): enough to slow down someone probing secrets;
- per contact, of messages processed by the worker (one process).
"""

import threading
import time
from collections import deque
from collections.abc import Callable

from django.http import HttpRequest

MAX_IPS = 10_000  # bound on memory: past it, the oldest entries are forgotten


class WindowLimiter:
    """At most `limit` hits per key within `window_s` seconds."""

    def __init__(
        self, limit: int = 20, window_s: float = 60.0, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self.limit = limit
        self.window_s = window_s
        self.clock = clock
        self._failures: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def blocked(self, ip: str) -> bool:
        """Has this key reached `limit` hits within the window?"""
        with self._lock:
            failures = self._failures.get(ip)
            if failures is None:
                return False
            self._prune(failures)
            if not failures:
                del self._failures[ip]
            return len(failures) >= self.limit

    def hit(self, key: str) -> bool:
        """Record one hit; True if it goes over the limit."""
        self.record(key)
        with self._lock:
            return len(self._failures[key]) > self.limit

    def record(self, ip: str) -> None:
        with self._lock:
            failures = self._failures.pop(ip, None) or deque()
            self._prune(failures)
            failures.append(self.clock())
            self._failures[ip] = failures  # last inserted = most recently seen
            while len(self._failures) > MAX_IPS:
                del self._failures[next(iter(self._failures))]

    def _prune(self, failures: deque[float]) -> None:
        oldest = self.clock() - self.window_s
        while failures and failures[0] <= oldest:
            failures.popleft()


def client_ip(request: HttpRequest) -> str:
    """The caller's address. Behind Caddy (§14.3) it is the last X-Forwarded-For entry,
    the one Caddy itself sets; without a proxy, REMOTE_ADDR."""
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded:
        return str(forwarded.split(",")[-1].strip())
    return str(request.META.get("REMOTE_ADDR", ""))
