"""pydoit tasks for the staged Vivado project and bitstream flow."""

from __future__ import annotations

from pathlib import Path
import re
import shutil
import subprocess
import sys
from typing import TYPE_CHECKING, Any, TextIO

from doit.tools import config_changed

if TYPE_CHECKING:
    from config import ResolvedConfig


def _string(config: ResolvedConfig, key: str) -> str:
    value = config.get(key)
    if not isinstance(value, str) or not value:
        raise TypeError(f"{key} must be a non-empty string")
    return value


def _positive_int(config: ResolvedConfig, key: str) -> int:
    value = config.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise TypeError(f"{key} must be a positive integer")
    return value


def run_vivado(
    command: list[str],
    cwd: Path,
    project_dir: Path,
    recreate_project: bool = False,
) -> None:
    """Run one Vivado batch stage, recreating the generated project when requested."""

    if recreate_project:
        shutil.rmtree(project_dir, ignore_errors=True)
    project_dir.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(command, cwd=cwd, check=True)


_DESIGN_NAME_BLOCK = re.compile(
    r"# CHANGE DESIGN NAME HERE\s*\n"
    r"variable design_name\s*\n"
    r"set design_name\s+\S+"
)


def normalize_exported_tcl(text: str, repo_root: Path, bd_name: str) -> str:
    """Make Vivado's generated block-design Tcl reusable in any checkout."""

    replacement = f"""# The enclosing flow supplies the committed block-design name.
variable design_name
if {{[info exists ::BD_NAME]}} {{
   set design_name $::BD_NAME
}} else {{
   set design_name {bd_name}
}}"""
    normalized, replacements = _DESIGN_NAME_BLOCK.subn(replacement, text, count=1)
    if replacements != 1:
        raise RuntimeError(
            "Vivado export did not contain the expected design-name block; "
            "refusing to overwrite the committed Tcl"
        )

    # Vivado's generated Tcl contains trailing spaces and variable blank lines.
    # Canonicalize them so repeated exports are stable and pass diff checks.
    normalized = "\n".join(line.rstrip() for line in normalized.splitlines())
    normalized = normalized.rstrip() + "\n"

    forbidden_paths = (str(repo_root.resolve()), "/workspace/", "/home/")
    found = next((path for path in forbidden_paths if path in normalized), None)
    if found is not None:
        raise RuntimeError(
            f"Vivado export contains a machine-specific absolute path ({found}); "
            "refusing to overwrite the committed Tcl"
        )
    return normalized


def export_block_design(
    command: list[str],
    cwd: Path,
    raw_export: Path,
    committed_export: Path,
    repo_root: Path,
    bd_name: str,
    terminal: TextIO | None = None,
) -> None:
    """Export, normalize, compare, and update the committed block-design Tcl."""

    output: TextIO = terminal or sys.__stderr__ or sys.stderr
    raw_export.parent.mkdir(parents=True, exist_ok=True)
    raw_export.unlink(missing_ok=True)
    try:
        subprocess.run(command, cwd=cwd, check=True)
        if not raw_export.is_file():
            raise RuntimeError(f"Vivado did not create the expected export: {raw_export}")

        normalized = normalize_exported_tcl(
            raw_export.read_text(encoding="utf-8"), repo_root, bd_name
        )
        current = (
            committed_export.read_text(encoding="utf-8")
            if committed_export.is_file()
            else None
        )
        if current == normalized:
            output.write(
                f"INFO: {committed_export} is up to date with block design {bd_name}.\n"
            )
            output.flush()
            return

        output.write(
            "WARNING: committed block-design Tcl was out of date; "
            f"updating {committed_export}.\n"
        )
        output.flush()
        committed_export.parent.mkdir(parents=True, exist_ok=True)
        temporary = committed_export.with_suffix(f"{committed_export.suffix}.tmp")
        temporary.write_text(normalized, encoding="utf-8")
        temporary.replace(committed_export)
    finally:
        raw_export.unlink(missing_ok=True)


def _source_files(rtl_root: Path) -> list[Path]:
    source_roots = (rtl_root, rtl_root / "memory", rtl_root / "sp")
    return sorted(
        path
        for source_root in source_roots
        for pattern in ("*.vh", "*.v", "*.sv")
        for path in source_root.glob(pattern)
        if path.is_file()
    )


def create_tasks(config: ResolvedConfig) -> list[dict[str, Any]]:
    """Create the staged Vivado project, bitstream, and hardware-platform tasks."""

    repo_root = config.repo_root
    scripts = repo_root / "tools/hardware/vivado"
    rtl_root = config.repo_path("paths.hardware.rtl")
    constraints_root = config.repo_path("paths.hardware.constraints")
    vivado_build_root = config.repo_path("paths.build.hardware.vivado")
    bitstream_root = config.repo_path("paths.build.hardware.bitstream")
    platform_root = config.repo_path("paths.build.hardware.platform")

    vivado_command = _string(config, "tools.vivado.command")
    project_name = _string(config, "hardware.vivado.project_name")
    part = _string(config, "hardware.fpga.part")
    bd_name = _string(config, "hardware.vivado.bd_name")
    top_name = _string(config, "hardware.vivado.top")
    xsa_name = _string(config, "hardware.vivado.xsa_name")
    num_cores = _positive_int(config, "architecture.num_cores")
    jobs = _positive_int(config, "hardware.vivado.jobs")

    project_dir = vivado_build_root / project_name
    xdc_file = constraints_root / "zedboard.xdc"
    project_file = project_dir / f"{project_name}.xpr"
    bd_file = project_dir / f"{project_name}.srcs/sources_1/bd/{bd_name}/{bd_name}.bd"
    wrapper_file = (
        project_dir
        / f"{project_name}.gen/sources_1/bd/{bd_name}/hdl/{top_name}.v"
    )
    synthesis_checkpoint = project_dir / f"{project_name}.runs/synth_1/{top_name}.dcp"
    implementation_checkpoint = (
        project_dir / f"{project_name}.runs/impl_1/{top_name}_routed.dcp"
    )
    bitstream = bitstream_root / f"{top_name}.bit"
    xsa = platform_root / f"{xsa_name}.xsa"

    common_args = [
        "-project-dir",
        str(project_dir),
        "-project-name",
        project_name,
        "-part",
        part,
        "-bd-name",
        bd_name,
        "-top",
        top_name,
        "-rtl-dir",
        str(rtl_root),
        "-xdc-file",
        str(xdc_file),
        "-bitstream-dir",
        str(bitstream_root),
        "-platform-dir",
        str(platform_root),
        "-xsa-name",
        xsa_name,
        "-export-file",
        str(project_dir / ".gpgpu" / f"{bd_name}.raw.tcl"),
        "-num-cores",
        str(num_cores),
        "-jobs",
        str(jobs),
    ]

    def command(script_name: str) -> list[str]:
        return [
            vivado_command,
            "-mode",
            "batch",
            "-source",
            str(scripts / script_name),
            "-tclargs",
            *common_args,
        ]

    stage_commands = {
        "project": command("create_project.tcl"),
        "block-design": command("create_block_design.tcl"),
        "synthesis": command("synthesis.tcl"),
        "implementation": command("implementation.tcl"),
        "bitstream": command("bitstream.tcl"),
        "xsa": command("export_hardware.tcl"),
        "export-block-design": command("export_block_design.tcl"),
    }
    source_files = _source_files(rtl_root)
    common_script = scripts / "common.tcl"
    exported_bd_script = scripts / f"{bd_name}.tcl"
    raw_bd_export = project_dir / ".gpgpu" / f"{bd_name}.raw.tcl"

    return [
        {
            "name": "vivado:project",
            "actions": [
                (
                    run_vivado,
                    [stage_commands["project"], repo_root, project_dir, True],
                )
            ],
            "file_dep": [
                str(common_script),
                str(scripts / "create_project.tcl"),
                *(str(path) for path in source_files),
                str(xdc_file),
            ],
            "targets": [str(project_file)],
            "uptodate": [config_changed({"command": stage_commands["project"]})],
            "clean": True,
        },
        {
            "name": "vivado:block-design",
            "actions": [
                (run_vivado, [stage_commands["block-design"], repo_root, project_dir])
            ],
            "task_dep": ["vivado:project"],
            "file_dep": [
                str(common_script),
                str(scripts / "create_block_design.tcl"),
                str(exported_bd_script),
            ],
            "targets": [str(bd_file), str(wrapper_file)],
            "uptodate": [config_changed({"command": stage_commands["block-design"]})],
            "clean": True,
        },
        {
            "name": "vivado:synthesis",
            "actions": [
                (run_vivado, [stage_commands["synthesis"], repo_root, project_dir])
            ],
            "task_dep": ["vivado:block-design"],
            "file_dep": [
                str(common_script),
                str(scripts / "synthesis.tcl"),
                str(wrapper_file),
            ],
            "targets": [str(synthesis_checkpoint)],
            "uptodate": [config_changed({"command": stage_commands["synthesis"]})],
            "clean": True,
        },
        {
            "name": "vivado:implementation",
            "actions": [
                (run_vivado, [stage_commands["implementation"], repo_root, project_dir])
            ],
            "task_dep": ["vivado:synthesis"],
            "file_dep": [
                str(common_script),
                str(scripts / "implementation.tcl"),
                str(synthesis_checkpoint),
            ],
            "targets": [str(implementation_checkpoint)],
            "uptodate": [
                config_changed({"command": stage_commands["implementation"]})
            ],
            "clean": True,
        },
        {
            "name": "vivado:bitstream",
            "actions": [
                (run_vivado, [stage_commands["bitstream"], repo_root, project_dir])
            ],
            "task_dep": ["vivado:implementation"],
            "file_dep": [
                str(common_script),
                str(scripts / "bitstream.tcl"),
                str(implementation_checkpoint),
            ],
            "targets": [str(bitstream)],
            "uptodate": [config_changed({"command": stage_commands["bitstream"]})],
            "clean": True,
        },
        {
            "name": "vivado:xsa",
            "actions": [
                (run_vivado, [stage_commands["xsa"], repo_root, project_dir])
            ],
            "task_dep": ["vivado:bitstream"],
            "file_dep": [
                str(common_script),
                str(scripts / "export_hardware.tcl"),
                str(bitstream),
            ],
            "targets": [str(xsa)],
            "uptodate": [config_changed({"command": stage_commands["xsa"]})],
            "clean": True,
        },
        {
            "name": "vivado:export-block-design",
            "actions": [
                (
                    export_block_design,
                    [
                        stage_commands["export-block-design"],
                        repo_root,
                        raw_bd_export,
                        exported_bd_script,
                        repo_root,
                        bd_name,
                    ],
                )
            ],
            "file_dep": [
                str(common_script),
                str(scripts / "export_block_design.tcl"),
            ],
            "uptodate": [False],
        },
        {
            "name": "vivado:all",
            "actions": None,
            "task_dep": ["vivado:xsa"],
        },
    ]
