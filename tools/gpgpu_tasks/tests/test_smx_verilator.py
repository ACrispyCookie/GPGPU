from pathlib import Path
import sys
import pytest
from tools.tests import rtl


class Config:
    def __init__(self, root):
        self.repo_root = root
        self.num_cores = 8
        self.trace = False
        self.verilator = "configured-verilator"

    @property
    def build_root(self):
        return self.repo_root / "custom-build"

    def get(self, key):
        return {
            "architecture.num_cores": self.num_cores,
            "tools.python.command": sys.executable,
            "tools.verilator.command": self.verilator,
            "tools.make.command": "configured-make",
            "tools.native_cxx.command": "configured-cxx",
            "tests.rtl.smx.trace": self.trace,
            "tests.rtl.range": "all",
            "tests.rtl.random.iterations": 2,
            "tests.rtl.random.seed": 12345,
        }[key]


def tasks(config):
    return {t["name"]: t for t in rtl.create_tasks(config)}


def test_real_checkout_verilator_sources_and_core_count():
    repo = Path(__file__).resolve().parents[3]
    config = Config(repo)
    graph = tasks(config)
    build = graph["tests:rtl:smx:build"]
    command = build["actions"][0][1][0]
    root = repo / "hardware/rtl/gpgpu"
    assert command[0] == "configured-verilator"
    assert all(Path(p).is_file() for p in build["file_dep"])
    for flag in ("--binary", "--timing", "--assert", "--autoflush", "-GNUM_CORES=8"):
        assert flag in command
    assert command[command.index("--top-module") + 1] == "tb_GPGPU_smx_only"
    assert command.index(str(root / "memory/MemoryInterface.sv")) < command.index(str(root / "GPGPU.sv"))
    for source in ("control/ExecutionController.sv", "sp/StreamingProcessor.sv"):
        assert str(root / source) in command
    assert str(root / "constants.svh") in build["file_dep"]
    assert str(root / "constants.svh") not in command
    assert not any("experimental" in s or "AXI4Lite" in s for s in command)
    assert not any(s in command for s in ("-P", "-s", "-Winfloop", "-Wno-timescale"))
    assert command[command.index("--Mdir") + 1] == str(config.build_root / "tests/rtl/smx")
    assert graph["tests:rtl:generate"]["actions"][1][1][0][-2:] == ["--num-cores", "8"]
    assert graph["tests:rtl:smx:run"]["actions"][0][1][0] == build["targets"]
    config.num_cores = 4
    config.verilator = "another-verilator"
    changed = tasks(config)
    assert "-GNUM_CORES=4" in changed["tests:rtl:smx:build"]["actions"][0][1][0]
    assert changed["tests:rtl:smx:build"]["uptodate"][0].config != build["uptodate"][0].config
    assert changed["tests:rtl:generate"]["uptodate"][0].config == {"num_cores": 4}


def test_e2e_deferred_and_aggregate_preserves_meaning():
    graph = tasks(Config(Path(__file__).resolve().parents[3]))
    for stage in ("build", "run", "all"):
        task = graph[f"tests:rtl:e2e:{stage}"]
        assert not task.get("task_dep")
        action = task["actions"][0]
        with pytest.raises(RuntimeError, match="E2E.*deferred"):
            action[0](*action[1])
    assert graph["tests:rtl:build"]["task_dep"] == ["tests:rtl:e2e:build", "tests:rtl:smx:build"]
    assert graph["tests:rtl:run"]["task_dep"] == ["tests:rtl:e2e:run", "tests:rtl:smx:run"]
    assert graph["tests:rtl:all"]["task_dep"] == ["tests:rtl:run"]


def test_trace_and_random_use_native_executable():
    config = Config(Path(__file__).resolve().parents[3])
    config.trace = True
    graph = tasks(config)
    assert "--trace" in graph["tests:rtl:smx:build"]["actions"][0][1][0]
    assert "+DUMP" in graph["tests:rtl:smx:run"]["actions"][0][1][0]
    command = graph["tests:rtl:random"]["actions"][0][1][0]
    assert "--vvp" not in command
    assert command[command.index("--simulator") + 1] == graph["tests:rtl:smx:build"]["targets"][0]
