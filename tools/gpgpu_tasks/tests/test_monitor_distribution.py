from pathlib import Path

import tomllib


def test_tasks_distribution_declares_monitor_rendering_dependency() -> None:
    root = Path(__file__).resolve().parents[1]
    package = tomllib.loads((root / "pyproject.toml").read_text())
    assert any(
        dependency.split(">", 1)[0].split("=", 1)[0] == "rich"
        for dependency in package["project"]["dependencies"]
    )
