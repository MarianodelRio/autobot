"""Ships structured logs to VictoriaLogs (DESIGN §7.3): never blocks, never raises,
and never logs through `logging` itself (that would recurse back into this handler)."""

import atexit
import contextlib
import json
import logging
import os
import queue
import sys
import threading
import time
from typing import Any

import httpx
from django.conf import settings

from autobot.ops.logging import record_dict

BATCH_LINES = 500
FLUSH_INTERVAL_S = 2.0
SEND_TIMEOUT_S = 2.0
FINAL_TIMEOUT_S = 1.0
STDERR_INTERVAL_S = 60.0


class VictoriaLogsHandler(logging.Handler):
    def __init__(
        self,
        url: str,
        *,
        batch_lines: int = BATCH_LINES,
        interval_s: float = FLUSH_INTERVAL_S,
        queue_size: int = 10_000,
    ) -> None:
        super().__init__()
        self.url = url.rstrip("/")
        self.batch_lines = batch_lines
        self.interval_s = interval_s
        self.client = httpx.Client()
        self.dropped = 0
        self._queue: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=queue_size)
        self._pid = 0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_stderr = 0.0
        self._closed = False
        self._ensure_thread()
        atexit.register(self._final_flush)

    def _ensure_thread(self) -> None:
        if self._thread is not None and self._thread.is_alive() and os.getpid() == self._pid:
            return
        self._pid = os.getpid()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def emit(self, record: logging.LogRecord) -> None:
        self._ensure_thread()
        data = record_dict(record)
        data["release"] = settings.RELEASE_SHA
        try:
            self._queue.put_nowait(data)
        except queue.Full:
            self.dropped += 1

    def _run(self) -> None:
        stop = self._stop
        batch: list[dict[str, Any]] = []
        deadline = time.monotonic() + self.interval_s
        while not stop.is_set():
            timeout = max(0.0, deadline - time.monotonic())
            with contextlib.suppress(queue.Empty):
                batch.append(self._queue.get(timeout=timeout))
            if not batch:
                deadline = time.monotonic() + self.interval_s
                continue
            if len(batch) >= self.batch_lines or time.monotonic() >= deadline:
                self._send(batch)
                batch = []
                deadline = time.monotonic() + self.interval_s

    def _send(self, batch: list[dict[str, Any]], *, timeout: float = SEND_TIMEOUT_S) -> None:
        body = "\n".join(json.dumps(item, ensure_ascii=False) for item in batch).encode()
        try:
            self.client.post(
                f"{self.url}/insert/jsonline?_stream_fields=service&_time_field=ts&_msg_field=msg",
                content=body,
                timeout=timeout,
            )
        except httpx.HTTPError:
            now = time.monotonic()
            if now - self._last_stderr >= STDERR_INTERVAL_S:
                print("victorialogs: send failed; batch discarded", file=sys.stderr)
                self._last_stderr = now

    def _final_flush(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._stop.set()
        remaining: list[dict[str, Any]] = []
        while True:
            try:
                remaining.append(self._queue.get_nowait())
            except queue.Empty:
                break
        if remaining:
            self._send(remaining, timeout=FINAL_TIMEOUT_S)

    def close(self) -> None:
        self._final_flush()
        super().close()
