from __future__ import annotations

import io
import json

from rich.console import Console
from src.run_logging import RunLogReporter
from src.run_monitor import RunMonitor


def test_runner_level_errors_are_recorded_and_visible_in_final_monitor(tmp_path):
    reporter = RunLogReporter(
        io.StringIO(), {}, repo_root=tmp_path, requested_task="demo:all"
    )
    reporter.initialize({}, [])
    reporter.runtime_error("cannot expand dependency graph")
    reporter.finalize(3)

    metadata = json.loads((reporter.run_dir / "run.json").read_text())
    assert metadata["error"] == "cannot expand dependency graph"
    output = io.StringIO()
    Console(file=output, width=80).print(RunMonitor(reporter.run_dir).render())
    assert "cannot expand dependency graph" in output.getvalue()
    assert "FAILED" in output.getvalue()
