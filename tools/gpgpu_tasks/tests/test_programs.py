from __future__ import annotations

from pathlib import Path
import shutil

import pytest
from tools.software import programs


class StubResolvedConfig:
    def __init__(self, repo_root: Path) -> None:
        self.repo_root = repo_root

    def get(self, key: str):
        values = {
            "paths.software.programs": "programs",
            "software.riscv.march": "rv32im",
            "software.riscv.abi": "ilp32",
            "tools.native_cc.command": "gcc",
            "tools.riscv_gcc.command": "/opt/riscv/bin/riscv64-unknown-elf-gcc",
        }
        return values[key]

    def repo_path(self, key: str) -> Path:
        assert key == "paths.software.root"
        return self.repo_root / "software"


def make_repo(tmp_path: Path) -> StubResolvedConfig:
    programs_dir = tmp_path / "software/programs"
    program_dir = programs_dir / "example"
    program_dir.mkdir(parents=True)
    (program_dir / "example.c").write_text("int main(void) { return 0; }\n")
    (programs_dir / "gpgpu.ld").write_text("SECTIONS {}\n")
    return StubResolvedConfig(tmp_path)


def tasks_by_name(config: StubResolvedConfig) -> dict[str, dict]:
    return {task["name"]: task for task in programs.create_tasks(config)}  # type: ignore[arg-type]


def test_create_tasks_preserves_makefile_build_graph_and_flags(tmp_path: Path) -> None:
    config = make_repo(tmp_path)
    tasks = tasks_by_name(config)
    prefix = "software:programs:example"

    assert set(tasks) == {
        f"{prefix}:x86",
        f"{prefix}:elf",
        f"{prefix}:dump",
        f"{prefix}:assembly",
        f"{prefix}:mem",
        f"{prefix}:riscv",
        f"{prefix}:all",
    }

    x86_command = tasks[f"{prefix}:x86"]["actions"][0][1][0]
    assert x86_command == [
        "gcc",
        "-O2",
        "-o",
        str(tmp_path / "software/programs/example/example_x86"),
        str(tmp_path / "software/programs/example/example.c"),
    ]

    elf_command = tasks[f"{prefix}:elf"]["actions"][0][1][0]
    assert elf_command[0] == "/opt/riscv/bin/riscv64-unknown-elf-gcc"
    assert "-march=rv32im" in elf_command
    assert "-mabi=ilp32" in elf_command
    assert "-ffixed-x31" in elf_command
    assert "-mno-relax" in elf_command
    assert f"-Wl,-T,{tmp_path / 'software/programs/gpgpu.ld'}" in elf_command
    assert f"-Wl,-Map,{tmp_path / 'software/programs/example/example.map'}" in elf_command

    assert tasks[f"{prefix}:dump"]["task_dep"] == [f"{prefix}:elf"]
    assert tasks[f"{prefix}:assembly"]["task_dep"] == [f"{prefix}:dump"]
    assert tasks[f"{prefix}:mem"]["task_dep"] == [f"{prefix}:dump"]
    assert tasks[f"{prefix}:riscv"]["task_dep"] == [f"{prefix}:assembly"]
    assert tasks[f"{prefix}:all"]["task_dep"] == [f"{prefix}:riscv", f"{prefix}:x86"]


def test_dump_transformations_match_makefile_filters(tmp_path: Path) -> None:
    dump = tmp_path / "example_dump_real.asm"
    assembly = tmp_path / "example_program.asm"
    memory = tmp_path / "example_instructions.mem"
    dump.write_text(
        """\
00000000 <_start>:
   0: 00000513 li a0,0
   4: 00b50533 add a0,a0,a1
   8: 8082 ret
not an instruction
""",
        encoding="utf-8",
    )

    programs.write_program_assembly(dump, assembly)
    programs.write_instruction_memory(dump, memory)

    assert assembly.read_text(encoding="utf-8") == (
        "li a0,0\n"
        "add a0,a0,a1\n"
        "ret\n"
    )
    assert memory.read_text(encoding="utf-8") == (
        "00000513\n"
        "00b50533\n"
    )


def test_non_program_directories_are_ignored(tmp_path: Path) -> None:
    config = make_repo(tmp_path)
    (tmp_path / "software/programs/not-a-program").mkdir()

    names = {task["name"] for task in programs.create_tasks(config)}  # type: ignore[arg-type]

    assert all("not-a-program" not in name for name in names)


@pytest.mark.skipif(shutil.which("gcc") is None, reason="gcc is not installed")
def test_x86_task_action_builds_a_real_executable(tmp_path: Path) -> None:
    config = make_repo(tmp_path)
    task = tasks_by_name(config)["software:programs:example:x86"]
    action, arguments = task["actions"][0]

    action(*arguments)

    executable = tmp_path / "software/programs/example/example_x86"
    assert executable.is_file()
    assert executable.stat().st_mode & 0o111
