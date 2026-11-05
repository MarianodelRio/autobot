"""VictoriaLogsHandler ships batched, scrubbed logs without blocking or recursing."""

import json
import logging
import queue
import time
from typing import Any

import httpx
import pytest

from autobot.ops.logship import VictoriaLogsHandler


def make_record(msg: str = "hello") -> logging.LogRecord:
    return logging.LogRecord("test", logging.INFO, __file__, 1, msg, (), None)


def mock_client(handler: VictoriaLogsHandler, responses: list[Any]) -> list[httpx.Request]:
    seen: list[httpx.Request] = []
    queued = list(responses)

    def responder(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        answer = queued.pop(0)
        if isinstance(answer, Exception):
            raise answer
        assert isinstance(answer, httpx.Response)
        return answer

    handler.client = httpx.Client(transport=httpx.MockTransport(responder))
    return seen


def wait_until(predicate: Any, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        time.sleep(0.01)


def test_sends_a_batch_once_it_reaches_batch_lines() -> None:
    handler = VictoriaLogsHandler(
        "http://vlogs.invalid", batch_lines=2, interval_s=10, queue_size=10
    )
    seen = mock_client(handler, [httpx.Response(200)])
    try:
        handler.emit(make_record())
        handler.emit(make_record())
        wait_until(lambda: seen)
    finally:
        handler.close()
    assert len(seen) == 1
    assert "_stream_fields=service&_time_field=ts&_msg_field=msg" in str(seen[0].url)
    assert len(seen[0].content.decode().splitlines()) == 2


def test_sends_a_partial_batch_after_the_interval() -> None:
    handler = VictoriaLogsHandler(
        "http://vlogs.invalid", batch_lines=500, interval_s=0.05, queue_size=10
    )
    seen = mock_client(handler, [httpx.Response(200)])
    try:
        handler.emit(make_record())
        wait_until(lambda: seen)
    finally:
        handler.close()
    assert len(seen) == 1
    assert len(seen[0].content.decode().splitlines()) == 1


def test_sent_payload_is_scrubbed_and_carries_the_release(settings: Any) -> None:
    settings.RELEASE_SHA = "abc123"
    handler = VictoriaLogsHandler(
        "http://vlogs.invalid", batch_lines=1, interval_s=10, queue_size=10
    )
    seen = mock_client(handler, [httpx.Response(200)])
    try:
        handler.emit(make_record("phone +34612345678"))
        wait_until(lambda: seen)
    finally:
        handler.close()
    payload = json.loads(seen[0].content.decode().splitlines()[0])
    assert payload["release"] == "abc123"
    assert payload["service"] and payload["ts"]
    assert "+34612345678" not in payload["msg"] and "5678" in payload["msg"]


class _FullQueue:
    """Simulates a saturated queue without racing the background thread."""

    def put_nowait(self, item: Any) -> None:
        raise queue.Full

    def get(self, timeout: float = 0) -> Any:
        raise queue.Empty

    def get_nowait(self) -> Any:
        raise queue.Empty


def test_dropped_counter_increments_when_the_queue_is_full() -> None:
    handler = VictoriaLogsHandler("http://vlogs.invalid", interval_s=100, queue_size=10)
    handler._queue = _FullQueue()  # type: ignore[assignment]
    try:
        handler.emit(make_record())
        handler.emit(make_record())
    finally:
        handler.close()
    assert handler.dropped == 2


def test_network_failure_is_swallowed_and_throttled_to_stderr(
    capsys: pytest.CaptureFixture[str],
) -> None:
    handler = VictoriaLogsHandler("http://vlogs.invalid", interval_s=100, queue_size=10)
    handler.client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: (_ for _ in ()).throw(httpx.ConnectError("down"))
        )
    )
    handler._send([{"msg": "one"}])
    handler._send([{"msg": "two"}])  # same minute: throttled, no second stderr line
    handler.close()
    err = capsys.readouterr().err
    assert err.count("victorialogs") == 1


def test_emit_failure_never_logs_through_logging_itself(
    capsys: pytest.CaptureFixture[str], caplog: pytest.LogCaptureFixture
) -> None:
    handler = VictoriaLogsHandler(
        "http://vlogs.invalid", batch_lines=1, interval_s=0.02, queue_size=10
    )
    handler.client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: (_ for _ in ()).throw(httpx.ConnectError("down"))
        )
    )
    logger = logging.getLogger("test-victorialogs-recursion")
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    try:
        with caplog.at_level(logging.DEBUG):
            logger.info("hello")
            time.sleep(0.2)
    finally:
        logger.removeHandler(handler)
        handler.close()
    assert "victorialogs" in capsys.readouterr().err
    # Only the original record propagated normally; the handler's own failure
    # never produced a second one (that would recurse back into this handler).
    assert [r.message for r in caplog.records] == ["hello"]
