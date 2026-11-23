"""A per-process circuit breaker for Google Calendar (ADR-023).

When Google is down or slow, every call holds a worker thread for its whole timeout. The
breaker watches the outcome of the calls of the process and, once it is clear that Google
is not answering, makes the next ones fail at once (the caller raises its transient
error) instead of waiting for a timeout each. After a pause one call is let through as a
probe: if it succeeds the breaker closes, if not it stays open another pause.

It opens when:
- `consecutive` calls in a row failed, or
- at least `ratio` of the calls of the last `window_s` seconds failed or were slow
  (longer than `slow_s`), with at least `min_calls` calls in the window.

Thread-safe (one lock), no I/O, no Django.
"""

import threading
import time
from collections import deque
from collections.abc import Callable


class CircuitBreaker:
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"

    def __init__(
        self,
        *,
        consecutive: int = 5,
        ratio: float = 0.5,
        min_calls: int = 10,
        window_s: float = 30.0,
        slow_s: float = 1.5,
        open_s: float = 8.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._consecutive_limit = consecutive
        self._ratio = ratio
        self._min_calls = min_calls
        self._window_s = window_s
        self._slow_s = slow_s
        self._open_s = open_s
        self._clock = clock
        self._lock = threading.Lock()
        self.reset()

    def reset(self) -> None:
        with self._lock:
            self._state = self.CLOSED
            self._failures_in_a_row = 0
            self._calls: deque[tuple[float, bool]] = deque()  # (when, bad)
            self._opened_at = 0.0
            self._probing = False

    @property
    def state(self) -> str:
        with self._lock:
            return self._state

    def allow(self) -> bool:
        """May a call go through? While open, no; once the pause is over, exactly one
        caller gets `True` (the probe) until it reports its outcome with `record` or
        `abort`."""
        with self._lock:
            if self._state == self.CLOSED:
                return True
            if self._state == self.OPEN:
                if self._clock() - self._opened_at < self._open_s:
                    return False
                self._state = self.HALF_OPEN
                self._probing = False
            if self._probing:  # half-open, and its probe is still running
                return False
            self._probing = True
            return True

    def record(self, *, ok: bool, duration_s: float) -> None:
        """The outcome of a call that `allow` let through. `ok` False is a failure of
        Google (timeout, network error, 5xx, quota); a refusal that Google answered
        quickly (a 404, a 403 denial) is `ok`."""
        now = self._clock()
        with self._lock:
            if self._state == self.HALF_OPEN:
                self._probing = False
                if ok:
                    self._close()
                else:
                    self._open(now)
                return
            if self._state == self.OPEN:
                return  # a call that started before it opened: nothing to learn
            self._failures_in_a_row = 0 if ok else self._failures_in_a_row + 1
            self._calls.append((now, not ok or duration_s > self._slow_s))
            while self._calls and now - self._calls[0][0] > self._window_s:
                self._calls.popleft()
            bad = sum(1 for _, flag in self._calls if flag)
            if self._failures_in_a_row >= self._consecutive_limit or (
                len(self._calls) >= self._min_calls and bad >= self._ratio * len(self._calls)
            ):
                self._open(now)

    def abort(self) -> None:
        """A call that `allow` let through ended with no verdict on Google (a bug, a
        permanent error of our own): frees the probe slot without changing the state."""
        with self._lock:
            self._probing = False

    def _open(self, now: float) -> None:
        self._state = self.OPEN
        self._opened_at = now
        self._probing = False

    def _close(self) -> None:
        self._state = self.CLOSED
        self._failures_in_a_row = 0
        self._calls.clear()
        self._probing = False
