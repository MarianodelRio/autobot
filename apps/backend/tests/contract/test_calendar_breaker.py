"""The Calendar circuit breaker (ADR-023): open, half-open and close, and basic thread safety."""

import threading

from integrations.google_calendar import CircuitBreaker


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def breaker(
    clock: Clock,
    *,
    consecutive: int = 5,
    ratio: float = 0.5,
    min_calls: int = 10,
    window_s: float = 30.0,
    slow_s: float = 1.5,
    open_s: float = 8.0,
) -> CircuitBreaker:
    return CircuitBreaker(
        consecutive=consecutive,
        ratio=ratio,
        min_calls=min_calls,
        window_s=window_s,
        slow_s=slow_s,
        open_s=open_s,
        clock=clock,
    )


def test_it_opens_after_consecutive_failures() -> None:
    clock = Clock()
    b = breaker(clock, consecutive=5)
    for _ in range(4):
        assert b.allow()
        b.record(ok=False, duration_s=0.1)
    assert b.state == "closed"
    b.record(ok=False, duration_s=0.1)
    assert b.state == "open" and not b.allow()


def test_a_success_resets_the_consecutive_count() -> None:
    b = breaker(Clock(), consecutive=3, min_calls=100)
    for _ in range(2):
        b.record(ok=False, duration_s=0.1)
    b.record(ok=True, duration_s=0.1)
    for _ in range(2):
        b.record(ok=False, duration_s=0.1)
    assert b.state == "closed"


def test_it_opens_on_a_share_of_failed_or_slow_calls_in_the_window() -> None:
    clock = Clock()
    b = breaker(clock, consecutive=99, min_calls=10, ratio=0.5, slow_s=1.5)
    for i in range(10):  # five ok and five slow-but-ok: half are bad
        b.record(ok=True, duration_s=2.0 if i % 2 else 0.1)
        clock.now += 1
    assert b.state == "open"


def test_too_few_calls_never_open_it() -> None:
    b = breaker(Clock(), consecutive=99, min_calls=10)
    for _ in range(9):
        b.record(ok=False, duration_s=5)
    # nine failures in a row but under both limits (consecutive=99, min_calls=10)
    assert b.state == "closed"


def test_old_calls_leave_the_window() -> None:
    clock = Clock()
    b = breaker(clock, consecutive=99, min_calls=10, window_s=30)
    for _ in range(9):
        b.record(ok=False, duration_s=0.1)
    clock.now += 31
    for _ in range(9):
        b.record(ok=True, duration_s=0.1)
    b.record(ok=True, duration_s=0.1)
    assert b.state == "closed"


def test_half_open_lets_one_probe_through_and_closes_on_success() -> None:
    clock = Clock()
    b = breaker(clock, consecutive=1, open_s=8)
    b.record(ok=False, duration_s=0.1)
    assert not b.allow()
    clock.now = 7.9
    assert not b.allow()
    clock.now = 8.0
    assert b.allow() and b.state == "half_open"
    assert not b.allow()  # only one probe at a time
    b.record(ok=True, duration_s=0.1)
    assert b.state == "closed" and b.allow()


def test_a_failed_probe_reopens_for_another_pause() -> None:
    clock = Clock()
    b = breaker(clock, consecutive=1, open_s=8)
    b.record(ok=False, duration_s=0.1)
    clock.now = 8.0
    assert b.allow()
    b.record(ok=False, duration_s=0.1)
    assert b.state == "open" and not b.allow()
    clock.now = 15.9
    assert not b.allow()
    clock.now = 16.0
    assert b.allow()


def test_an_aborted_probe_frees_the_slot() -> None:
    clock = Clock()
    b = breaker(clock, consecutive=1, open_s=8)
    b.record(ok=False, duration_s=0.1)
    clock.now = 8.0
    assert b.allow()
    b.abort()
    assert b.allow()


def test_threads_share_it_without_losing_calls() -> None:
    b = CircuitBreaker(consecutive=10_000, min_calls=10_000_000)

    def hammer() -> None:
        for _ in range(500):
            if b.allow():
                b.record(ok=False, duration_s=0.01)

    threads = [threading.Thread(target=hammer) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert b.state == "closed"
    # 4000 failures recorded under the lock: the consecutive count is exact
    assert b._failures_in_a_row == 4000
