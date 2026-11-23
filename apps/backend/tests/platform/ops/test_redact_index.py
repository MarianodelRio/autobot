"""`redact` indexes every tenant secret once per registry, not once per log line."""

import logging
import time
from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import SecretStr

from autobot.ops import logging as ops_logging
from autobot.ops.logging import PrivacyFilter, record_dict, redact
from autobot.tenancy import registry


class FakeRegistry:
    def __init__(self, *tokens: str) -> None:
        self.tenants = [
            SimpleNamespace(secrets=SimpleNamespace(token=SecretStr(token))) for token in tokens
        ]


@pytest.fixture(autouse=True)
def current(monkeypatch: pytest.MonkeyPatch) -> Iterator[dict[str, Any]]:
    holder: dict[str, Any] = {"registry": None}
    monkeypatch.setattr(registry, "loaded_registry", lambda: holder["registry"])
    ops_logging._index_cache.clear()
    yield holder
    ops_logging._index_cache.clear()


def test_secret_added_by_a_reload_is_redacted(current: dict[str, Any]) -> None:
    current["registry"] = FakeRegistry("old-secret-aaaa")
    assert redact("x old-secret-aaaa y") == "x [REDACTED] y"
    assert redact("x new-secret-bbbb y") == "x new-secret-bbbb y"
    current["registry"] = FakeRegistry("old-secret-aaaa", "new-secret-bbbb")
    assert redact("x new-secret-bbbb y") == "x [REDACTED] y"
    current["registry"] = FakeRegistry("new-secret-bbbb")
    assert redact("x old-secret-aaaa y") == "x old-secret-aaaa y"


def test_index_is_built_once_per_registry(
    current: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    builds = []
    original = ops_logging._SecretIndex

    def counting(secrets: Any) -> Any:
        builds.append(1)
        return original(secrets)

    monkeypatch.setattr(ops_logging, "_SecretIndex", counting)
    first = current["registry"] = FakeRegistry("secret-one-1111")
    for _ in range(5):
        redact("secret-one-1111")
    assert len(builds) == 1
    second = current["registry"] = FakeRegistry("secret-two-2222")
    redact("a")
    assert len(builds) == 2
    current["registry"] = first  # a pinned job on the older snapshot: no rebuild
    redact("a")
    current["registry"] = second
    redact("a")
    assert len(builds) == 2


def test_changed_settings_secret_rebuilds(settings: Any) -> None:
    settings.NOTIFY_BOT_TOKEN = "notify-token-1"
    assert redact("notify-token-1") == "[REDACTED]"
    settings.NOTIFY_BOT_TOKEN = "notify-token-2"
    assert redact("notify-token-1") == "notify-token-1"
    assert redact("notify-token-2") == "[REDACTED]"


def test_overlapping_secrets_leave_no_fragment(current: dict[str, Any]) -> None:
    current["registry"] = FakeRegistry("abcdefgh", "efghijkl", "mnopqrst")
    assert redact("1 abcdefghijkl 2") == "1 [REDACTED] 2"
    assert redact("abcdefgh|efghijkl") == "[REDACTED]|[REDACTED]"
    assert redact("mnopqrstmnopqrst") == "[REDACTED]"
    assert redact("abcdefgh") == "[REDACTED]"


def test_prefix_shared_secrets_and_short_secrets(current: dict[str, Any]) -> None:
    current["registry"] = FakeRegistry("tok_abcdef", "tok_abcdefXYZ", "ab")
    assert redact("t tok_abcdefXYZ t") == "t [REDACTED] t"
    assert redact("t tok_abcdef! t") == "t [REDACTED]! t"
    assert redact("zabz") == "z[REDACTED]z"


def test_record_is_scrubbed_once(current: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    current["registry"] = FakeRegistry("secret-one-1111")
    record = logging.LogRecord("x", logging.INFO, __file__, 1, "token secret-one-1111", (), None)
    PrivacyFilter().filter(record)
    calls = []

    def spy(value: str) -> str:
        calls.append(value)
        return value

    monkeypatch.setattr(ops_logging, "redact", spy)
    assert record_dict(record)["msg"] == "token [REDACTED]"
    assert calls == []


def test_redact_is_fast_with_thousands_of_tenants(current: dict[str, Any]) -> None:
    # The cost must not grow with the number of tenants (the old one was O(N) per line).
    # Compared against a 3-tenant registry on the same machine, so a loaded CI runner
    # does not make it flaky; the old implementation was ~50x slower at 3000.
    line = "Delivered message to tenant tenant-00042-secret-token after 120 ms status=ok " * 2

    def per_line(tenants: int) -> float:
        current["registry"] = FakeRegistry(
            *(f"tenant-{i:05d}-secret-token" for i in range(tenants))
        )
        assert "tenant-00042" not in redact(line)
        best = float("inf")
        for _ in range(3):
            started = time.perf_counter()
            for _ in range(300):
                redact(line)
            best = min(best, (time.perf_counter() - started) / 300)
        return best

    small, large = per_line(50), per_line(3000)
    assert large < small * 5
    assert large < 0.005
