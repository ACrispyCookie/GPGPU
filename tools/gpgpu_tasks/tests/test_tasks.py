from __future__ import annotations

from doit.cmd_base import TaskLoader2

from tasks import GPGPUTaskLoader, create_task_loader, run


def test_loader_implements_task_loader_v2_and_starts_without_tasks() -> None:
    loader = create_task_loader()

    assert isinstance(loader, TaskLoader2)
    assert isinstance(loader, GPGPUTaskLoader)
    assert loader.API == 2
    assert loader.load_doit_config() == {}
    assert loader.load_tasks(cmd=None, pos_args=[]) == []


def test_empty_task_project_can_be_executed_programmatically() -> None:
    assert run(["list"]) == 0
