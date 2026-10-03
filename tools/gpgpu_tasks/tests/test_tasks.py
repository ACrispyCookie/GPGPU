from __future__ import annotations

from pathlib import Path

from doit.cmd_base import TaskLoader2

from src import GPGPUTaskLoader, create_task_loader, run


class StubResolvedConfig:
    def __init__(self, repo_root: Path, build_path: Path) -> None:
        self.repo_root = repo_root
        self.build_path = build_path

    @property
    def build_root(self) -> Path:
        return self.build_path


def make_config(tmp_path: Path) -> StubResolvedConfig:
    task_module = tmp_path / "tools/software/programs.py"
    task_module.parent.mkdir(parents=True)
    task_module.write_text("def create_tasks(config):\n    return []\n", encoding="utf-8")
    rtl_module = tmp_path / "tools/tests/rtl.py"
    rtl_module.parent.mkdir(parents=True)
    rtl_module.write_text(
        "def create_tasks(config):\n"
        "    return [{'name': 'tests:rtl:all', 'actions': None}]\n",
        encoding="utf-8",
    )
    vivado_module = tmp_path / "tools/hardware/vivado/tasks.py"
    vivado_module.parent.mkdir(parents=True)
    vivado_module.write_text(
        "def create_tasks(config):\n"
        "    return [{'name': 'vivado:project', 'actions': None}]\n",
        encoding="utf-8",
    )
    return StubResolvedConfig(tmp_path, tmp_path / "build")


def test_loader_stores_resolved_config_and_configures_dep_file(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    loader = create_task_loader(config)  # type: ignore[arg-type]

    assert isinstance(loader, TaskLoader2)
    assert isinstance(loader, GPGPUTaskLoader)
    assert loader.API == 2
    assert loader.resolved_config is config
    assert loader.load_doit_config() == {
        "dep_file": str(tmp_path / "build/.doit.db"),
        "backend": "sqlite3",
    }
    assert (tmp_path / "build").is_dir()
    assert [task.name for task in loader.load_tasks(cmd=None, pos_args=[])] == [
        "tests:rtl:all",
        "vivado:project",
    ]


def test_empty_task_project_can_be_executed_programmatically(tmp_path: Path) -> None:
    build_path = tmp_path / "build"
    build_path.mkdir()
    config = make_config(tmp_path)

    assert run(config, ["list"]) == 0  # type: ignore[arg-type]
