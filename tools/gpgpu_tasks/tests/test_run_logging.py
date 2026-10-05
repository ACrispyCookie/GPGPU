from __future__ import annotations

import json
from pathlib import Path

from src import run_logged_task


class StubResolvedConfig:
    def __init__(self, repo_root: Path) -> None:
        self.repo_root = repo_root

    @property
    def build_root(self) -> Path:
        return self.repo_root / "build"


def make_task_repo(tmp_path: Path) -> StubResolvedConfig:
    programs = tmp_path / "tools/software/programs.py"
    programs.parent.mkdir(parents=True)
    programs.write_text(
        "import subprocess\n"
        "import sys\n"
        "\n"
        "def first():\n"
        "    print('python output from first', flush=True)\n"
        "    subprocess.run([sys.executable, '-c', \"print('child output from first', flush=True)\"], check=True)\n"
        "\n"
        "def second():\n"
        "    subprocess.run([sys.executable, '-c', \"import sys; print('child failure output', flush=True); sys.exit(7)\"], check=True)\n"
        "\n"
        "def success():\n"
        "    print('successful output', flush=True)\n"
        "\n"
        "def create_tasks(config):\n"
        "    return [\n"
        "        {'name': 'demo:first', 'actions': [first], 'uptodate': [False]},\n"
        "        {'name': 'demo:second', 'actions': [second], 'task_dep': ['demo:first'], 'uptodate': [False]},\n"
        "        {'name': 'demo:third', 'actions': [lambda: None], 'task_dep': ['demo:second'], 'uptodate': [False]},\n"
        "        {'name': 'demo:all', 'actions': None, 'task_dep': ['demo:third']},\n"
        "        {'name': 'success:stage', 'actions': [success], 'uptodate': [False]},\n"
        "        {'name': 'success:all', 'actions': None, 'task_dep': ['success:stage']},\n"
        "    ]\n",
        encoding="utf-8",
    )
    for relative_path in (
        "tools/tests/rtl.py",
        "tools/hardware/vivado/tasks.py",
        "tools/hardware/vitis/tasks.py",
    ):
        module = tmp_path / relative_path
        module.parent.mkdir(parents=True, exist_ok=True)
        module.write_text("def create_tasks(config):\n    return []\n", encoding="utf-8")
    return StubResolvedConfig(tmp_path)


def test_failed_run_streams_and_records_each_task_in_dependency_order(
    tmp_path: Path, capfd
) -> None:
    config = make_task_repo(tmp_path)

    status = run_logged_task(config, "demo:all")  # type: ignore[arg-type]

    assert status == 2
    terminal_output = capfd.readouterr()
    combined_output = terminal_output.out + terminal_output.err
    assert "python output from first" in combined_output
    assert "child output from first" in combined_output
    assert "child failure output" in combined_output

    runs = list((tmp_path / "logs/runs").iterdir())
    assert len(runs) == 1
    run_dir = runs[0]
    assert run_dir.name.endswith("_demo-all")
    assert (tmp_path / "logs/latest").resolve() == run_dir
    assert (tmp_path / "logs/last-failed").resolve() == run_dir

    first_log = run_dir / "00_first.log"
    second_log = run_dir / "01_second.log"
    assert "python output from first" in first_log.read_text(encoding="utf-8")
    assert "child output from first" in first_log.read_text(encoding="utf-8")
    assert "child failure output" in second_log.read_text(encoding="utf-8")
    assert not (run_dir / "02_third.log").exists()

    metadata = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    assert metadata["run_id"] == run_dir.name
    assert metadata["requested_task"] == "demo:all"
    assert metadata["started_at"]
    assert metadata["finished_at"]
    assert metadata["exit_code"] == 7
    assert isinstance(metadata["git_dirty"], bool)
    assert metadata["tasks"][0] == {
        "task": "demo:first",
        "status": "success",
        "duration_s": metadata["tasks"][0]["duration_s"],
        "log": "00_first.log",
    }
    assert metadata["tasks"][0]["duration_s"] >= 0
    assert metadata["tasks"][1]["task"] == "demo:second"
    assert metadata["tasks"][1]["status"] == "failed"
    assert metadata["tasks"][1]["exit_code"] == 7
    assert metadata["tasks"][1]["duration_s"] >= 0
    assert metadata["tasks"][1]["log"] == "01_second.log"
    assert metadata["tasks"][2] == {"task": "demo:third", "status": "not_run"}


def test_successful_run_updates_latest_without_replacing_last_failed(tmp_path: Path) -> None:
    config = make_task_repo(tmp_path)
    assert run_logged_task(config, "demo:all") == 2  # type: ignore[arg-type]
    failed_run = (tmp_path / "logs/last-failed").resolve()

    assert run_logged_task(config, "success:all") == 0  # type: ignore[arg-type]

    successful_run = (tmp_path / "logs/latest").resolve()
    assert successful_run != failed_run
    assert (tmp_path / "logs/last-failed").resolve() == failed_run
    metadata = json.loads((successful_run / "run.json").read_text(encoding="utf-8"))
    assert metadata["exit_code"] == 0
    assert metadata["tasks"][0]["status"] == "success"
    assert metadata["tasks"][0]["log"] == "00_stage.log"
    assert "successful output" in (successful_run / "00_stage.log").read_text(
        encoding="utf-8"
    )


def test_python_validation_failure_is_visible_in_task_log_and_metadata(tmp_path: Path, capfd) -> None:
    config = make_task_repo(tmp_path)
    (tmp_path / "tools/software/programs.py").write_text(
        "def validate():\n"
        "    print('Platform Build Finished successfully.', flush=True)\n"
        "    raise FileNotFoundError('Vitis completed without producing required artifacts: missing.bit')\n"
        "def create_tasks(config):\n"
        "    return [{'name': 'validate:all', 'actions': [validate]}]\n",
        encoding="utf-8",
    )
    assert run_logged_task(config, "validate:all") == 2
    output = capfd.readouterr()
    message = "Vitis completed without producing required artifacts: missing.bit"
    assert message in output.out + output.err
    run_dir = (tmp_path / "logs/last-failed").resolve()
    metadata = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    task = metadata["tasks"][0]
    assert message in (run_dir / task["log"]).read_text(encoding="utf-8")
    assert message in task["error"]
