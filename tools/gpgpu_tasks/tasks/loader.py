"""TaskLoader2 implementation and programmatic pydoit runner."""

from __future__ import annotations

from collections.abc import Sequence

from doit.cmd_base import TaskLoader2
from doit.doit_cmd import DoitMain
from doit.task import Task


class GPGPUTaskLoader(TaskLoader2):
    """Load GPGPU tasks through pydoit's task-loader v2 API."""

    def load_doit_config(self) -> dict[str, object]:
        """Return project-level pydoit configuration."""

        return {}

    def load_tasks(self, cmd: object, pos_args: list[str]) -> list[Task]:
        """Create the task graph; it is intentionally empty for now."""

        return []


def create_task_loader() -> GPGPUTaskLoader:
    """Create the GPGPU task loader."""

    return GPGPUTaskLoader()


def run(arguments: Sequence[str] = ()) -> int:
    """Execute pydoit programmatically with the GPGPU task loader."""

    result = DoitMain(create_task_loader(), config_filenames=()).run(list(arguments))
    return 0 if result is None else result
