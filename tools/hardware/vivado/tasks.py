"""pydoit tasks for the staged Vivado project and bitstream flow."""

from __future__ import annotations

from pathlib import Path
import re
import shutil
import subprocess
import sys
from typing import TYPE_CHECKING, Any, TextIO

from doit.tools import config_changed
from src.project_paths import ProjectPaths

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


def _host_address(value: object, key: str) -> str:
    """Validate and canonicalize one 64-KiB-aligned 32-bit AXI base address."""

    if not isinstance(value, str) or re.fullmatch(r"0x[0-9A-Fa-f]{1,8}", value) is None:
        raise TypeError(f"{key} must be a hexadecimal string such as 0x41200000")
    numeric = int(value, 16)
    if numeric > 0xFFFFFFFF:
        raise ValueError(f"{key} must fit in a 32-bit address")
    if numeric % 0x10000 != 0:
        raise ValueError(f"{key} must be aligned to the 64-KiB AXI GPIO range")
    return f"0x{numeric:08X}"


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
_NUM_CORES_PROPERTY = re.compile(
    r"(CONFIG\.SP_PER_SM\s+)\{[^{}\r\n]+\}"
)
_HOST_ADDRESS_SEGMENTS = {
    "axi_gpio_address/S_AXI/Reg": "HOST_ADDRESS_GPIO",
    "axi_gpio_cmd/S_AXI/Reg": "HOST_CMD_GPIO",
    "axi_gpio_rdata/S_AXI/Reg": "HOST_RDATA_GPIO",
    "axi_gpio_status/S_AXI/Reg": "HOST_STATUS_GPIO",
    "axi_gpio_wdata/S_AXI/Reg": "HOST_WDATA_GPIO",
}


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

    # architecture.num_cores owns this value; do not snapshot a local build's
    # concrete core count into the portable committed block-design source.
    normalized = _NUM_CORES_PROPERTY.sub(r"\g<1>$::NUM_CORES", normalized)

    # hardware.vivado.host_interface owns these AXI offsets. Keep Vivado's
    # exported segment structure, but replace snapshot values with Tcl globals.
    for segment, variable in _HOST_ADDRESS_SEGMENTS.items():
        address = re.compile(
            rf"(assign_bd_address\s+-offset\s+)\S+"
            rf"(?=[^\r\n]*\[get_bd_addr_segs\s+{re.escape(segment)}\])"
        )
        normalized = address.sub(rf"\g<1>$::{variable}", normalized)

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
        if re.search(
            r"set\s+GPGPU_0\s+\[\s*create_bd_cell\s+"
            r"-type\s+module\s+-reference\s+"
            r"(?:GPGPU\s+GPGPU_0|\$block_name\s+\$block_cell_name)\s*\]",
            normalized,
        ) is None:
            raise RuntimeError(
                "Vivado export is missing the GPGPU module-reference cell GPGPU_0; "
                "refusing to overwrite the committed Tcl with an incomplete design."
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


def extract_block_design_if_present(
    command: list[str],
    cwd: Path,
    project_file: Path,
    bd_file: Path,
    raw_export: Path,
    committed_export: Path,
    repo_root: Path,
    bd_name: str,
    terminal: TextIO | None = None,
) -> None:
    """Refresh committed Tcl from an existing project, or bootstrap from Git."""

    output: TextIO = terminal or sys.__stderr__ or sys.stderr
    if not project_file.is_file():
        if not committed_export.is_file():
            raise RuntimeError(
                f"Neither the Vivado project nor committed block-design Tcl exists: "
                f"{committed_export}"
            )
        output.write(
            "INFO: no existing Vivado project; using the committed block-design "
            "Tcl as the first-clone bootstrap.\n"
        )
        output.flush()
        return

    if not bd_file.is_file():
        existing_designs = sorted(bd_file.parents[1].glob("*/*.bd"))
        if existing_designs:
            found = ", ".join(path.name for path in existing_designs)
            raise RuntimeError(
                f"Vivado project exists but does not contain {bd_name}.bd; found: "
                f"{found}. Rename the project block design or set "
                "hardware.vivado.bd_name before continuing."
            )
        if not committed_export.is_file():
            raise RuntimeError(
                f"Vivado project has no {bd_name}.bd and the committed bootstrap "
                f"does not exist: {committed_export}"
            )
        output.write(
            f"INFO: Vivado project has no saved {bd_name}.bd; using the committed "
            "Tcl as the bootstrap.\n"
        )
        output.flush()
        return

    export_block_design(
        command,
        cwd,
        raw_export,
        committed_export,
        repo_root,
        bd_name,
        terminal=output,
    )


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
    paths = ProjectPaths.from_config(config)
    scripts = repo_root / "tools/hardware/vivado"
    rtl_root = paths.hardware_rtl
    constraints_root = paths.hardware_constraints
    vivado_build_root = paths.vivado
    bitstream_root = paths.bitstream
    platform_root = paths.platform

    vivado_command = _string(config, "tools.vivado.command")
    project_name = _string(config, "hardware.vivado.project_name")
    part = _string(config, "hardware.fpga.part")
    bd_name = _string(config, "hardware.vivado.bd_name")
    top_name = _string(config, "hardware.vivado.top")
    xsa_name = _string(config, "hardware.vivado.xsa_name")
    num_cores = _positive_int(config, "architecture.num_cores")
    jobs = _positive_int(config, "hardware.vivado.jobs")
    host_address_keys = {
        "-host-address-gpio": "hardware.vivado.host_interface.address_gpio",
        "-host-cmd-gpio": "hardware.vivado.host_interface.cmd_gpio",
        "-host-rdata-gpio": "hardware.vivado.host_interface.rdata_gpio",
        "-host-status-gpio": "hardware.vivado.host_interface.status_gpio",
        "-host-wdata-gpio": "hardware.vivado.host_interface.wdata_gpio",
    }
    host_addresses = {
        flag: _host_address(config.get(key), key)
        for flag, key in host_address_keys.items()
    }
    if len(set(host_addresses.values())) != len(host_addresses):
        raise ValueError("hardware.vivado.host_interface addresses must be unique")

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
    for flag, address in host_addresses.items():
        common_args.extend([flag, address])

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
            "name": "vivado:extract-block-design",
            "actions": [
                (
                    extract_block_design_if_present,
                    [
                        stage_commands["export-block-design"],
                        repo_root,
                        project_file,
                        bd_file,
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
            "name": "vivado:project",
            "actions": [
                (
                    run_vivado,
                    [stage_commands["project"], repo_root, project_dir, True],
                )
            ],
            "task_dep": ["vivado:extract-block-design"],
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
