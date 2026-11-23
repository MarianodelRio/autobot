"""SlotLimiter: global rate, per-recipient interval, bounded waits, thread safety."""

from concurrent.futures import ThreadPoolExecutor

import pytest

from autobot.runtime.ratelimit import SlotLimiter


class Clock:
    def __init__(self) -> None:
        self.now = 0.0
        self.slept: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


def make(clock: Clock, **kwargs: float) -> SlotLimiter:
    params = {"rate_per_s": 10.0, "key_interval_s": 1.0, **kwargs}
    return SlotLimiter(clock=clock, sleep=clock.sleep, **params)


def test_first_use_is_immediate() -> None:
    clock = Clock()
    assert make(clock).acquire("a") is None and clock.slept == []


def test_global_rate_spaces_different_keys() -> None:
    clock = Clock()
    limiter = make(clock)
    for key in "abc":
        assert limiter.acquire(key) is None
    # 10/s: the slots were 0.1 s apart, so it slept 0.1 then 0.1 more
    assert clock.slept == pytest.approx([0.1, 0.1])


def test_per_key_interval_defers_when_the_wait_is_long() -> None:
    clock = Clock()
    limiter = make(clock, key_interval_s=30.0)
    assert limiter.acquire("a") is None
    wait = limiter.acquire("a")
    assert wait == pytest.approx(30.0) and clock.slept == []  # nothing slept or reserved
    assert limiter.acquire("b") is None  # another chat is not affected
    clock.now = 29.5
    assert limiter.acquire("a") is None  # 0.5 s is within max_wait: slept, then granted
    assert clock.slept[-1] == pytest.approx(0.5)


def test_short_wait_is_slept_and_long_wait_is_returned() -> None:
    clock = Clock()
    limiter = make(clock, max_wait_s=0.5)
    assert limiter.acquire("a") is None
    assert limiter.acquire("a") == pytest.approx(1.0) and clock.slept == []
    clock.now = 0.6
    assert limiter.acquire("a") is None and clock.slept == pytest.approx([0.4])


def test_a_deferred_caller_reserves_nothing() -> None:
    clock = Clock()
    limiter = make(clock, key_interval_s=100.0)
    limiter.acquire("a")
    first = limiter.acquire("a")
    second = limiter.acquire("a")
    assert first == pytest.approx(100.0) and second == pytest.approx(100.0)
    clock.now = 100.0
    assert limiter.acquire("a") is None


def test_threads_never_share_a_slot() -> None:
    limiter = SlotLimiter(rate_per_s=1000.0, key_interval_s=0.0, max_wait_s=5.0)
    # Real clock and sleep: 50 grants at 1000/s must all succeed (waits <= 0.05 s).
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda i: limiter.acquire(str(i)), range(50)))
    assert results == [None] * 50


def test_forgets_old_keys() -> None:
    clock = Clock()
    limiter = make(clock)
    for i in range(10_005):
        clock.now += 2.0
        limiter.acquire(str(i))
    assert len(limiter._next_by_key) <= 10_001
