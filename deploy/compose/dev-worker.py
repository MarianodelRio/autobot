"""Local-only supervisor for the Procrastinate workers (compose.local.yaml).

Runs the worker command as a child and restarts it when a Python file under /app/src
changes (what `watchfiles` did), but, unlike the `watchfiles` CLI, it exits when the
child dies by itself (e.g. after PostgreSQL restarted). The container then stops and
Docker's restart policy brings it back, instead of staying "Up" with no worker.

Usage: dev-worker.py <command> [args...]
SIGTERM/SIGINT are forwarded to the child for a graceful stop (it takes no new jobs and
lets the running ones finish), then this process exits.
"""

import signal
import subprocess
import sys
import threading

from watchfiles import PythonFilter, watch

WATCH_PATH = "/app/src"
STOP_TIMEOUT = 55  # the child's own graceful timeout is 50 s; Docker's, 60 s


def stop(child: subprocess.Popen[bytes]) -> None:
    if child.poll() is not None:
        return
    child.terminate()
    try:
        child.wait(timeout=STOP_TIMEOUT)
    except subprocess.TimeoutExpired:
        child.kill()
        child.wait()


def main(command: list[str]) -> int:
    stopping = threading.Event()

    def request_stop(signum: int, frame: object) -> None:
        stopping.set()

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)

    child = subprocess.Popen(command)
    while not stopping.is_set():
        # Yields an empty set every second without changes, so a dead child is noticed.
        for changes in watch(
            WATCH_PATH,
            watch_filter=PythonFilter(),
            stop_event=stopping,
            rust_timeout=1000,
            yield_on_timeout=True,
        ):
            if child.poll() is not None:
                code = child.returncode
                print(f"dev-worker: child exited with {code}; exiting", flush=True)
                return code or 1
            if changes:
                print("dev-worker: code changed; restarting the worker", flush=True)
                stop(child)
                child = subprocess.Popen(command)
    stop(child)
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("usage: dev-worker.py <command> [args...]")
    sys.exit(main(sys.argv[1:]))
