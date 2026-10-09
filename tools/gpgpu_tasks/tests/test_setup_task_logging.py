"""Ordered setup tasks must remain visible in the build monitor and stage logs."""

import json

from src import run_logged_task
from test_run_logging import make_task_repo


def test_setup_stage_is_logged_between_dependencies_and_requested_task(tmp_path):
    config = make_task_repo(tmp_path)
    (tmp_path / "tools/software/programs.py").write_text(
        "def create_tasks(config):\n"
        "    return [\n"
        "        {'name': 'board:reset', 'actions': [lambda: print('reset stage')], 'uptodate': [False]},\n"
        "        {'name': 'board:mode', 'actions': [lambda: print('mode stage')], 'uptodate': [False]},\n"
        "        {'name': 'board:program', 'actions': [lambda: print('program stage')], "
        "'task_dep': ['board:reset'], 'setup': ['board:mode'], 'uptodate': [False]},\n"
        "    ]\n"
    )
    assert run_logged_task(config, "board:program", monitor=False) == 0
    run_dir = (tmp_path / "logs/latest").resolve()
    metadata = json.loads((run_dir / "run.json").read_text())
    assert [task["task"] for task in metadata["tasks"]] == [
        "board:reset", "board:mode", "board:program",
    ]
    assert all(task["status"] == "success" for task in metadata["tasks"])
    assert "mode stage" in (run_dir / "01_mode.log").read_text()
