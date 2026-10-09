from __future__ import annotations

import io
import json
from datetime import datetime, timezone

from rich.console import Console


def render(monitor, *, width=100, height=30):
    output = io.StringIO()
    console = Console(file=output, width=width, height=height, color_system=None)
    console.print(monitor.render(width=width, height=height))
    return output.getvalue()


def test_json_monitor_renders_stage_progress_and_elapsed(tmp_path):
    from src.run_monitor import RunMonitor

    snapshot = {
        "requested_task": "fpga:all",
        "exit_code": None,
        "tasks": [
            {"task": "vivado:project", "status": "success", "duration_s": 2.5},
            {"task": "vitis:project", "status": "up_to_date"},
            {
                "task": "vitis:build",
                "status": "running",
                "started_at": "2026-01-01T00:00:00+00:00",
            },
            {"task": "fpga:upload", "status": "not_run"},
        ],
    }
    (tmp_path / "run.json").write_text(json.dumps(snapshot))
    monitor = RunMonitor(
        tmp_path, now=lambda: datetime(2026, 1, 1, 0, 0, 10, tzinfo=timezone.utc)
    )
    text = render(monitor)
    for expected in [
        "GPGPU Build Monitor",
        "fpga:all",
        "RUNNING",
        "2/4",
        "✓",
        "2.5s",
        "UP TO DATE",
        "●",
        "10.0s",
        "○",
        "vivado:project",
        "vitis:project",
    ]:
        assert expected in text
    snapshot["exit_code"] = 7
    snapshot["tasks"][2].update(status="failed", duration_s=12)
    (tmp_path / "run.json").write_text(json.dumps(snapshot))
    assert "FAILED" in render(monitor)
    assert "✗" in render(monitor)
    assert "12.0s" in render(monitor)


def test_retains_valid_json_snapshot_on_missing_partial_or_invalid_read(tmp_path):
    from src.run_monitor import RunMonitor

    monitor = RunMonitor(tmp_path)
    assert "Waiting" in render(monitor)
    path = tmp_path / "run.json"
    path.write_text(
        json.dumps({"requested_task": "saved", "exit_code": 0, "tasks": []})
    )
    assert "SUCCESS" in render(monitor)
    for invalid in ["{", "[]", '{"tasks": [42]}', '{"tasks": "broken"}']:
        path.write_text(invalid)
        assert "saved" in render(monitor)
    path.unlink()
    assert "saved" in render(monitor)


def test_log_tail_is_bounded_and_dashboard_fits_short_narrow_terminal(tmp_path):
    from src.run_monitor import RunMonitor

    (tmp_path / "stage.log").write_text(
        "OLD_SENTINEL" + "x" * 100000 + "\n" + "\n".join(f"line {i}" for i in range(30))
    )
    (tmp_path / "run.json").write_text(
        json.dumps(
            {
                "requested_task": "demo",
                "exit_code": None,
                "tasks": [
                    {"task": "demo:stage", "status": "running", "log": "stage.log"}
                ],
            }
        )
    )
    monitor = RunMonitor(tmp_path)
    assert "line 29" in render(monitor, height=12)
    assert "OLD_SENTINEL" not in render(monitor)
    assert "line 0\n" not in render(monitor, height=12)
    for width, height in [(25, 6), (12, 3), (80, 12), (1, 1)]:
        text = render(monitor, width=width, height=height)
        assert len(text.splitlines()) <= height
        assert all(len(line) <= width for line in text.splitlines())


def test_interrupted_and_unreadable_log(tmp_path):
    from src.run_monitor import RunMonitor

    (tmp_path / "run.json").write_text(
        json.dumps(
            {
                "requested_task": "demo",
                "exit_code": 130,
                "tasks": [
                    {
                        "task": "demo:stage",
                        "status": "interrupted",
                        "duration_s": 3,
                        "log": "missing.log",
                    }
                ],
            }
        )
    )
    assert "INTERRUPTED" in render(RunMonitor(tmp_path))


def test_invalid_stage_fields_do_not_replace_last_valid_snapshot(tmp_path):
    from src.run_monitor import RunMonitor

    path = tmp_path / "run.json"
    path.write_text(json.dumps({"requested_task": "good", "tasks": []}))
    monitor = RunMonitor(tmp_path)
    assert "good" in render(monitor)
    for changes in [{"status": []}, {"started_at": 42}, {"duration_s": "oops"}]:
        task = {"task": "bad", "status": "running", **changes}
        path.write_text(json.dumps({"requested_task": "bad", "tasks": [task]}))
        assert "good" in render(monitor)


def test_terminal_open_failure_closes_duplicated_fd(tmp_path, monkeypatch):
    import os

    from src.run_monitor import BuildDashboard

    before = len(list(__import__("pathlib").Path("/proc/self/fd").iterdir()))
    failures = []

    def cannot_open(*args, **kwargs):
        raise OSError("terminal failure")

    monkeypatch.setattr(os, "fdopen", cannot_open)
    dashboard = BuildDashboard(tmp_path, lambda: failures.append(True))
    assert not dashboard.start()
    dashboard.stop()
    assert failures
    assert len(list(__import__("pathlib").Path("/proc/self/fd").iterdir())) == before


def test_tail_reads_at_most_64k_and_uses_latest_or_active_json_reference(
    tmp_path, monkeypatch
):
    from pathlib import Path

    from src.run_monitor import RunMonitor

    log = tmp_path / "huge.log"
    log.write_bytes(b"x" * 200000 + b"\nlatest huge line\n")
    (tmp_path / "new.log").write_text("new log line")
    path = tmp_path / "run.json"
    path.write_text(
        json.dumps(
            {
                "requested_task": "demo",
                "tasks": [
                    {"task": "old", "status": "running", "log": "huge.log"},
                    {"task": "new", "status": "success", "log": "new.log"},
                ],
            }
        )
    )
    real_open = Path.open
    reads = []

    class BoundedReader:
        def __init__(self, handle):
            self.handle = handle

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.handle.close()

        def seek(self, *args):
            return self.handle.seek(*args)

        def tell(self):
            return self.handle.tell()

        def read(self, size=-1):
            reads.append((self.tell(), size))
            assert 0 <= size <= 65536
            return self.handle.read(size)

    def opened(self, *args, **kwargs):
        handle = real_open(self, *args, **kwargs)
        return BoundedReader(handle) if self == log else handle

    monkeypatch.setattr(Path, "open", opened)
    monitor = RunMonitor(tmp_path)
    assert "latest huge line" in render(monitor)
    assert reads == [(log.stat().st_size - 65536, 65536)]
    snapshot = json.loads(path.read_text())
    snapshot["tasks"][0]["status"] = "success"
    path.write_text(json.dumps(snapshot))
    assert "new log line" in render(monitor)
    assert len(reads) == 1
