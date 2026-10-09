from __future__ import annotations

import io
import json
from datetime import datetime, timezone

from rich.console import Console
from src.run_monitor import RunMonitor


def render(tmp_path, snapshot, *, height=24, width=80):
    (tmp_path / "run.json").write_text(json.dumps(snapshot))
    output = io.StringIO()
    Console(file=output, width=width, height=height, color_system=None).print(
        RunMonitor(
            tmp_path, now=lambda: datetime(2026, 1, 1, tzinfo=timezone.utc)
        ).render(width=width, height=height)
    )
    return output.getvalue()


def test_progress_bar_counts_completed_and_cached_stages(tmp_path):
    snapshot = {
        "requested_task": "vitis:build:all",
        "exit_code": None,
        "tasks": [
            {"task": "vivado:project", "status": "success", "duration_s": 2.0},
            {"task": "vivado:block-design:run", "status": "up_to_date"},
            {"task": "vivado:synthesis", "status": "running"},
            {"task": "vitis:build:host", "status": "not_run"},
        ],
    }
    text = render(tmp_path, snapshot)
    assert "50%" in text
    assert "█" in text and "░" in text


def test_stage_symbols_have_distinct_terminal_styles(tmp_path):
    snapshot = {
        "requested_task": "demo:all",
        "tasks": [
            {"task": "demo:done", "status": "success", "duration_s": 1},
            {"task": "demo:active", "status": "running"},
            {"task": "demo:pending", "status": "not_run"},
        ],
    }
    (tmp_path / "run.json").write_text(json.dumps(snapshot))
    from rich.color import Color
    from rich.text import Text

    output = io.StringIO()
    console = Console(
        file=output, width=80, force_terminal=True, color_system="standard"
    )
    console.print(RunMonitor(tmp_path).render())
    text = Text.from_ansi(output.getvalue())
    done = text.get_style_at_offset(console, text.plain.index("✓"))
    active = text.get_style_at_offset(console, text.plain.index("●"))
    pending = text.get_style_at_offset(console, text.plain.index("○"))
    assert done.color is not None and done.color.number == Color.parse("green").number
    assert (
        active.color is not None
        and active.color.number == Color.parse("cyan").number
        and active.bold
    )
    assert pending.dim


def test_single_stage_slot_keeps_active_stage_visible(tmp_path):
    (tmp_path / "stage.log").write_text("INFO: current output\n")
    snapshot = {
        "requested_task": "demo:all",
        "exit_code": None,
        "tasks": [
            {"task": "demo:first", "status": "success"},
            {"task": "demo:second", "status": "success"},
            {"task": "demo:active", "status": "running", "log": "stage.log"},
            {"task": "demo:next", "status": "not_run"},
            {"task": "demo:last", "status": "not_run"},
        ],
    }
    text = render(tmp_path, snapshot, height=9, width=60)
    assert "● demo:active" in text
    assert "current output" in text
    assert len(text.splitlines()) <= 9


def test_many_stages_keep_live_log_visible_in_short_terminal(tmp_path):
    (tmp_path / "stage.log").write_text("INFO: newest live line\n")
    tasks = [
        {"task": f"stage:{i}", "status": "success", "duration_s": 1} for i in range(10)
    ]
    tasks[8].update(status="running", log="stage.log")
    tasks[9]["status"] = "not_run"
    text = render(
        tmp_path,
        {"requested_task": "demo:all", "tasks": tasks, "exit_code": None},
        height=14,
        width=60,
    )
    assert "stage:8" in text
    assert "Live log" in text
    assert "newest live line" in text
    assert len(text.splitlines()) <= 14
