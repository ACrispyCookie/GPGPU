from __future__ import annotations

import importlib.util
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[3]
MODULE_PATH = REPO_ROOT / "software/programs/fpga_run.py"
SPEC = importlib.util.spec_from_file_location("test_fpga_run", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
fpga_run = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = fpga_run
SPEC.loader.exec_module(fpga_run)


def test_program_adapter_visualization_writes_under_artifact_directory(
    tmp_path: Path, monkeypatch
) -> None:
    program_dir = tmp_path / "software/programs/example"
    artifact_dir = tmp_path / "external-build/software/programs/example"
    program_dir.mkdir(parents=True)
    visualize_script = program_dir / "visualize.py"
    visualize_script.write_text("print('visualize')\n", encoding="utf-8")
    calls: list[tuple[list[str], Path, bool]] = []

    def fake_run(command: list[str], *, cwd: Path, check: bool) -> None:
        calls.append((command, cwd, check))

    monkeypatch.setattr(fpga_run.subprocess, "run", fake_run)
    adapter = fpga_run.ProgramAdapter(program_dir, artifact_dir)

    adapter.finalize(visualize=True, adapter_args=object())  # type: ignore[arg-type]

    assert artifact_dir.is_dir()
    assert calls == [([sys.executable, str(visualize_script)], artifact_dir, True)]
    assert not (program_dir / "data.csv").exists()


def test_loaded_program_adapter_uses_build_root_for_runtime_outputs(tmp_path: Path) -> None:
    adapter = fpga_run.load_adapter("nbody", tmp_path / "external-build")

    expected = tmp_path / "external-build/software/programs/nbody"
    assert adapter.artifact_dir == expected
    assert adapter.imem_path() == expected / "nbody_instructions.mem"
    assert adapter.csv_path == expected / "data.csv"
