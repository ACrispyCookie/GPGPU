from __future__ import annotations

import json

import pytest

from src import run_logged_task
from test_run_logging import make_task_repo


@pytest.mark.parametrize("monitor", [False, True])
@pytest.mark.parametrize("aggregate", [False, True])
@pytest.mark.parametrize("exception, exit_code", [("RuntimeError", 3), ("InvalidTask", 2)])
def test_uptodate_exception_is_attributed_before_action(tmp_path, capfd, monitor, aggregate, exception, exit_code):
    config = make_task_repo(tmp_path)
    actions = "None" if aggregate else "[lambda: print('MUST NOT EXECUTE')]"
    (tmp_path / "tools/software/programs.py").write_text(
        "from doit.exceptions import InvalidTask\n"
        "def saved_current(task, values):\n"
        f"    raise {exception}('snapshot callback exploded')\n"
        "def create_tasks(config):\n"
        "    return [\n"
        "        {'name': 'flow:prior', 'actions': [lambda: print('prior success')], 'uptodate': [False]},\n"
        f"        {{'name': 'flow:broken', 'actions': {actions}, 'task_dep': ['flow:prior'], 'uptodate': [saved_current]}},\n"
        "        {'name': 'flow:pending', 'actions': [lambda: print('MUST NOT EXECUTE')], 'task_dep': ['flow:broken']},\n"
        "        {'name': 'flow:all', 'actions': None, 'task_dep': ['flow:pending']},\n"
        "    ]\n"
    )

    assert run_logged_task(config, "flow:all", monitor=monitor) == exit_code
    output = capfd.readouterr()
    assert "snapshot callback exploded" in output.out + output.err
    assert "MUST NOT EXECUTE" not in output.out
    run_dir = (tmp_path / "logs/latest").resolve()
    snapshot = json.loads((run_dir / "run.json").read_text())
    assert snapshot["exit_code"] == exit_code
    tasks = {task["task"]: task for task in snapshot["tasks"]}
    assert tasks["flow:prior"]["status"] == "success"
    assert "error" not in tasks["flow:prior"]
    failed = tasks["flow:broken"]
    assert failed["status"] == "failed"
    assert failed["exit_code"] == exit_code
    assert "snapshot callback exploded" in failed["error"]
    assert "Traceback (most recent call last)" in failed["error"]
    assert "saved_current" in failed["error"]
    assert "started_at" not in failed  # Its action never started.
    assert tasks["flow:pending"] == {"task": "flow:pending", "status": "not_run"}
    assert "snapshot callback exploded" in snapshot["error"]
    diagnostics = (run_dir / "diagnostics.log").read_text()
    assert "flow:broken" in diagnostics
    assert "saved_current" in diagnostics
    assert "snapshot callback exploded" in diagnostics
    assert "snapshot callback exploded" in (run_dir / failed["log"]).read_text()
    assert "snapshot callback exploded" not in (run_dir / tasks["flow:prior"]["log"]).read_text()
    assert (tmp_path / "logs/last-failed").resolve() == run_dir


def test_unattributed_runtime_error_does_not_relabel_completed_task(tmp_path):
    import io

    from doit.task import Task
    from src.run_logging import RunLogReporter

    output = io.StringIO()
    reporter = RunLogReporter(output, {}, repo_root=tmp_path, requested_task="flow:all")
    prior = Task("flow:prior", [lambda: None])
    pending = Task("flow:pending", [lambda: None], task_dep=[prior.name])
    reporter.initialize({prior.name: prior, pending.name: pending}, [pending.name])
    try:
        reporter.get_status(prior)
        reporter.execute_task(prior)
        reporter.add_success(prior)
        reporter.runtime_error("dependency dispatcher exploded")
        reporter.complete_run()
    finally:
        reporter.finalize(2)

    snapshot = json.loads((reporter.run_dir / "run.json").read_text())
    assert [task["status"] for task in snapshot["tasks"]] == ["success", "not_run"]
    assert snapshot["error"] == "dependency dispatcher exploded"
    assert snapshot["exit_code"] == 2
    assert "dependency dispatcher exploded" in output.getvalue()
    assert "ERROR: runner" in (reporter.run_dir / "diagnostics.log").read_text()
    assert "dependency dispatcher exploded" not in (reporter.run_dir / snapshot["tasks"][0]["log"]).read_text()


def test_dependency_error_before_action_does_not_require_start_time(tmp_path, capfd):
    config = make_task_repo(tmp_path)
    (tmp_path / "tools/software/programs.py").write_text(
        "def create_tasks(config):\n"
        "    return [\n"
        "        {'name': 'broken', 'actions': [lambda: print('MUST NOT EXECUTE')], 'file_dep': [str(config.repo_root / 'missing.input')]},\n"
        "        {'name': 'all', 'actions': None, 'task_dep': ['broken']},\n"
        "    ]\n"
    )
    assert run_logged_task(config, "all") == 2
    output = capfd.readouterr()
    assert "missing.input" in output.out + output.err
    assert "KeyError" not in output.out + output.err
    snapshot = json.loads((tmp_path / "logs/latest/run.json").read_text())
    failed = snapshot["tasks"][0]
    assert failed["status"] == "failed"
    assert "missing.input" in failed["error"]
    assert "started_at" not in failed
    assert "duration_s" not in failed
    assert "missing.input" in (tmp_path / "logs/latest" / failed["log"]).read_text()
