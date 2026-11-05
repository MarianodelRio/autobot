"""Limit per IP of invalid webhook signatures and the conversation lock
hash."""

import uuid

import pytest
from django.test import RequestFactory

from autobot.channels import ratelimit
from autobot.channels.ratelimit import WindowLimiter, client_ip
from autobot.runtime.locks import contact_hash, conversation_lock


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_an_ip_is_blocked_after_the_limit_within_the_window() -> None:
    clock = Clock()
    limiter = WindowLimiter(limit=3, window_s=60, clock=clock)
    for _ in range(2):
        limiter.record("a")
    assert not limiter.blocked("a")
    limiter.record("a")
    assert limiter.blocked("a") and not limiter.blocked("b")
    clock.now = 60.0  # the first failures leave the window
    assert not limiter.blocked("a")


def test_memory_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ratelimit, "MAX_IPS", 2)
    limiter = WindowLimiter(limit=1)
    for ip in ("a", "b", "c"):
        limiter.record(ip)
    assert not limiter.blocked("a")  # forgotten, the oldest
    assert limiter.blocked("b") and limiter.blocked("c")


def test_client_ip_behind_caddy() -> None:
    factory = RequestFactory()
    assert client_ip(factory.get("/", REMOTE_ADDR="10.0.0.2")) == "10.0.0.2"
    forwarded = factory.get("/", REMOTE_ADDR="10.0.0.2", HTTP_X_FORWARDED_FOR="1.1.1.1, 2.2.2.2")
    assert client_ip(forwarded) == "2.2.2.2"


def test_lock_hash_has_no_identifier_and_depends_on_tenant_and_channel() -> None:
    tenant = uuid.UUID("01920000-0000-7000-8000-00000000000a")
    lock = conversation_lock(tenant, "main", "34600000001")
    assert lock.startswith("conv:") and len(lock) == 21 and "34600000001" not in lock
    assert contact_hash(tenant, "main", "1") != contact_hash(tenant, "test", "1")
    assert contact_hash(tenant, "main", "1") != contact_hash(uuid.uuid7(), "main", "1")
    assert lock == conversation_lock(tenant, "main", "34600000001")


def test_hit_counts_and_reports_going_over() -> None:
    limiter = WindowLimiter(limit=2, clock=Clock())
    assert [limiter.hit("c") for _ in range(3)] == [False, False, True]
