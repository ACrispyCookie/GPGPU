"""Explicit board-VM operations on existing FPGA artifacts (no vendor builds)."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any

from src.project_paths import ProjectPaths

if TYPE_CHECKING:
    from config import ResolvedConfig


def upload_artifacts(
    artifacts: tuple[tuple[Path, str], ...],
    command: str,
    destination: str,
    directory: str,
    cwd: Path,
    configured_names: tuple[tuple[str, Any], ...] = (),
) -> None:
    """Copy artifacts with explicit remote filenames using argv-based SCP."""
    if not isinstance(command, str) or not re.fullmatch(r"(?!-)[A-Za-z0-9_./-]+", command):
        raise ValueError("tools.scp.command must be a single nonempty executable without arguments")
    if not isinstance(destination, str) or not re.fullmatch(
        r"(?:[A-Za-z0-9_.][A-Za-z0-9_.-]*@)?[A-Za-z0-9_.][A-Za-z0-9_.-]*", destination
    ):
        raise ValueError("hardware.fpga.upload.destination must be a safe SSH hostname or user@hostname")
    if (
        not isinstance(directory, str)
        or not re.fullmatch(r"/[A-Za-z0-9_./-]*", directory)
        or any(part in (".", "..") for part in directory.split("/"))
    ):
        raise ValueError("hardware.fpga.upload.directory must be an absolute safe POSIX path without traversal")
    # Validate raw configured names as well as derived filenames: suffixing an
    # empty or non-string platform/host must not turn it into an accepted name.
    names = (*configured_names, *(("hardware.fpga.upload.filenames", filename) for _, filename in artifacts))
    for key, name in names:
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]*", name):
            raise ValueError(f"{key} must be a nonempty safe single basename without traversal")
    missing = [str(source) for source, _ in artifacts if not source.is_file()]
    if missing:
        raise FileNotFoundError("Missing FPGA upload artifacts:\n" + "\n".join(missing))
    for source, filename in artifacts:
        remote = f"{destination}:{PurePosixPath(directory) / filename}"
        print(f"Uploading {source} -> {remote}", flush=True)
        subprocess.run([command, "--", str(source), remote], cwd=cwd, check=True)


def create_tasks(config: ResolvedConfig) -> list[dict[str, Any]]:
    """Create the independent FPGA task namespace, extensible with board commands."""
    paths = ProjectPaths.from_config(config)
    platform = config.get("hardware.vitis.platform_name")
    host = config.get("hardware.vitis.host_name")
    top = config.get("hardware.vivado.top")
    artifacts = (
        (paths.bitstream / f"{top}.bit", f"{platform}.bit"),
        (paths.vitis / f"{platform}" / "export" / f"{platform}" / "hw/sdt/ps7_init.tcl", "ps7_init.tcl"),
        (paths.vitis / f"{host}" / "build" / f"{host}.elf", f"{host}.elf"),
    )
    return [
        {
            "name": "fpga:upload",
            "task_dep": [],
            "uptodate": [False],
            "actions": [
                (
                    upload_artifacts,
                    [
                        artifacts,
                        config.get("tools.scp.command"),
                        config.get("hardware.fpga.upload.destination"),
                        config.get("hardware.fpga.upload.directory"),
                        paths.repo_root,
                        (("hardware.vitis.platform_name", platform), ("hardware.vitis.host_name", host)),
                    ],
                )
            ],
        }
    ]
