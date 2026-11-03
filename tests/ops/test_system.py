"""Pure readers of host metrics and operational state files, against a fake /proc."""

import json
import shutil
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from autobot.ops import system


def test_cpu_percent_computes_delta_between_two_reads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stat = tmp_path / "stat"
    stat.write_text("cpu  100 0 100 700 0 0 0 0 0 0\nother ignored\n")

    def fake_sleep(_: float) -> None:
        stat.write_text("cpu  200 0 200 800 0 0 0 0 0 0\n")

    monkeypatch.setattr(time, "sleep", fake_sleep)
    # total 900 -> 1200 (+300), idle 700 -> 800 (+100): 1 - 100/300 busy.
    assert system.cpu_percent(root=tmp_path, interval=0) == pytest.approx(200 / 3)


def test_cpu_percent_without_change_is_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "stat").write_text("cpu  100 0 100 700 0 0 0 0 0 0\n")
    monkeypatch.setattr(time, "sleep", lambda _: None)
    assert system.cpu_percent(root=tmp_path, interval=0) == 0.0


def test_cpu_percent_missing_file_is_none(tmp_path: Path) -> None:
    assert system.cpu_percent(root=tmp_path, interval=0) is None


def test_memory_used_percent(tmp_path: Path) -> None:
    (tmp_path / "meminfo").write_text("MemTotal:        1000 kB\nMemAvailable:     250 kB\n")
    assert system.memory(root=tmp_path) == 75.0


def test_memory_missing_file_is_none(tmp_path: Path) -> None:
    assert system.memory(root=tmp_path) is None


def test_load_first_figure(tmp_path: Path) -> None:
    (tmp_path / "loadavg").write_text("0.42 0.38 0.35 1/200 1234\n")
    assert system.load(root=tmp_path) == 0.42


def test_load_missing_file_is_none(tmp_path: Path) -> None:
    assert system.load(root=tmp_path) is None


def test_uptime_first_figure(tmp_path: Path) -> None:
    (tmp_path / "uptime").write_text("12345.67 98765.43\n")
    assert system.uptime_s(root=tmp_path) == 12345.67


def test_uptime_missing_file_is_none(tmp_path: Path) -> None:
    assert system.uptime_s(root=tmp_path) is None


def test_disk_used_percent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        shutil, "disk_usage", lambda _: SimpleNamespace(total=100, used=42, free=58)
    )
    assert system.disk("/") == 42.0


def test_disk_missing_path_is_none(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(_: str) -> Any:
        raise OSError("no such path")

    monkeypatch.setattr(shutil, "disk_usage", boom)
    assert system.disk("/missing") is None


def test_read_backup_status_missing_is_none(tmp_path: Path) -> None:
    assert system.read_backup_status(tmp_path) is None


def test_read_backup_status_corrupt_is_none(tmp_path: Path) -> None:
    (tmp_path / "backup.json").write_text("not json")
    assert system.read_backup_status(tmp_path) is None


def test_read_backup_status_parses(tmp_path: Path) -> None:
    (tmp_path / "backup.json").write_text(json.dumps({"finished_at": "now", "ok": True}))
    assert system.read_backup_status(tmp_path) == {"finished_at": "now", "ok": True}


def test_read_deploys_missing_file_is_empty(tmp_path: Path) -> None:
    assert system.read_deploys(tmp_path) == []


def test_read_deploys_ignores_corrupt_lines_and_respects_limit(tmp_path: Path) -> None:
    lines = [json.dumps({"at": i, "result": "deployed"}) for i in range(3)]
    lines.insert(1, "not json")
    lines.append("")
    (tmp_path / "deploys.jsonl").write_text("\n".join(lines))
    deploys = system.read_deploys(tmp_path, limit=2)
    assert [d["at"] for d in deploys] == [1, 2]
