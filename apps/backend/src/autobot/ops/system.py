"""Pure readers of host metrics and operational state files; no Django."""

import json
import os
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

PROC = Path("/proc")


def _read(path: Path) -> str | None:
    try:
        return path.read_text()
    except OSError:
        return None


def cpu_percent(root: Path = PROC, interval: float = 0.2) -> float | None:
    def totals() -> tuple[int, int] | None:
        text = _read(root / "stat")
        if text is None:
            return None
        for line in text.splitlines():
            if line.startswith("cpu "):
                try:
                    fields = [int(field) for field in line.split()[1:]]
                except ValueError:
                    return None
                if len(fields) < 5:
                    return None
                return sum(fields), fields[3] + fields[4]  # total, idle + iowait
        return None

    first = totals()
    if first is None:
        return None
    time.sleep(interval)
    second = totals()
    if second is None:
        return None
    total_delta = second[0] - first[0]
    if total_delta <= 0:
        return 0.0
    idle_delta = second[1] - first[1]
    return max(0.0, min(100.0, (1 - idle_delta / total_delta) * 100))


def memory(root: Path = PROC) -> float | None:
    text = _read(root / "meminfo")
    if text is None:
        return None
    values: dict[str, int] = {}
    for line in text.splitlines():
        key, _, rest = line.partition(":")
        if key in ("MemTotal", "MemAvailable"):
            try:
                values[key] = int(rest.split()[0])
            except IndexError, ValueError:
                return None
    total = values.get("MemTotal")
    available = values.get("MemAvailable")
    if not total or available is None:
        return None
    return max(0.0, min(100.0, (1 - available / total) * 100))


def load(root: Path = PROC) -> float | None:
    text = _read(root / "loadavg")
    if text is None:
        return None
    try:
        return float(text.split()[0])
    except IndexError, ValueError:
        return None


def uptime_s(root: Path = PROC) -> float | None:
    text = _read(root / "uptime")
    if text is None:
        return None
    try:
        return float(text.split()[0])
    except IndexError, ValueError:
        return None


def swap(root: Path = PROC) -> float | None:
    """Percent of swap in use; 0.0 on a host without swap."""
    text = _read(root / "meminfo")
    if text is None:
        return None
    values: dict[str, int] = {}
    for line in text.splitlines():
        key, _, rest = line.partition(":")
        if key in ("SwapTotal", "SwapFree"):
            try:
                values[key] = int(rest.split()[0])
            except IndexError, ValueError:
                return None
    total = values.get("SwapTotal")
    free = values.get("SwapFree")
    if total is None or free is None:
        return None
    if total <= 0:
        return 0.0
    return max(0.0, min(100.0, (1 - free / total) * 100))


def _statvfs(path: str) -> os.statvfs_result | None:
    try:
        return os.statvfs(path)
    except OSError:
        return None


def disk(path: str = "/") -> float | None:
    """Percent of the filesystem a non-root process can no longer use. `shutil.disk_usage`
    (used / total) ignores ext4's root-reserved blocks, so PostgreSQL (not root) hits
    ENOSPC while it still reads below the critical threshold: `f_bavail` is what is left
    for it."""
    stat = _statvfs(path)
    if stat is None or stat.f_blocks <= 0:
        return None
    return max(0.0, min(100.0, (1 - stat.f_bavail / stat.f_blocks) * 100))


def inodes(path: str = "/") -> float | None:
    """Percent of inodes in use (as seen by a non-root process); `None` on filesystems
    without a fixed inode table (`f_files` is 0 there)."""
    stat = _statvfs(path)
    if stat is None or stat.f_files <= 0:
        return None
    return max(0.0, min(100.0, (1 - stat.f_favail / stat.f_files) * 100))


def read_backup_status(state_dir: Path) -> dict[str, Any] | None:
    text = _read(state_dir / "backup.json")
    if text is None:
        return None
    try:
        data: Any = json.loads(text)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def read_prune_status(state_dir: Path) -> dict[str, Any] | None:
    """`backup-prune.json`, written by backup.sh from the prune marker snapshots."""
    text = _read(state_dir / "backup-prune.json")
    if text is None:
        return None
    try:
        data: Any = json.loads(text)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.utcoffset() is not None else None


def prune_overdue(status: dict[str, Any] | None, now: datetime, limit: timedelta) -> bool:
    """True when the last prune (or, if there never was one, the oldest snapshot) is older
    than `limit`. No file, or no snapshot at all, is not an alert: nothing to prune yet."""
    if status is None:
        return False
    reference = parse_time(status.get("last_prune_at")) or parse_time(
        status.get("oldest_snapshot_at")
    )
    return reference is not None and now - reference > limit


def read_deploys(state_dir: Path, limit: int = 20) -> list[dict[str, Any]]:
    text = _read(state_dir / "deploys.jsonl")
    if text is None:
        return []
    deploys: list[dict[str, Any]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            deploys.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return deploys[-limit:]
