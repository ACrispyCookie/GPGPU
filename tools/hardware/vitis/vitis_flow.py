"""Vitis Python CLI entry point for component builds.

Run through the vendor launcher, for example:
    vitis -s vitis_flow.py -- build --workspace <path> --component <name>
"""

from __future__ import annotations

from pathlib import Path
import argparse
import shutil
import sys

import vitis


def installed_rsa_archive() -> Path:
    """Locate the GNU RSA input in the SDK that provided the active Vitis API."""
    module_file = getattr(vitis, "__file__", None)
    if module_file:
        for parent in Path(module_file).resolve().parents:
            services = parent / "data/embeddedsw/lib/sw_services"
            if not services.is_dir():
                continue
            exact = services / "xilrsa/src/librsa.a"
            if exact.is_file():
                return exact
            candidates = sorted(services.glob("xilrsa_v*/src/librsa.a"))
            if len(candidates) == 1:
                return candidates[0]
            if len(candidates) > 1:
                raise RuntimeError(f"Ambiguous installed RSA archives: {candidates}")
    raise FileNotFoundError(
        "Missing vendor input xilrsa/src/librsa.a. Could not locate it in "
        "data/embeddedsw/lib/sw_services of the active Vitis SDK. "
        "Check that the matching Vitis embedded software installation is complete."
    )


def prepare_bsp_output_directories(component_root: Path) -> None:
    """Restore BSP directories and SDK inputs omitted by portable archives."""
    for cmake_source in component_root.rglob("CMakeLists.txt"):
        bsp_root = cmake_source.parent
        if not (bsp_root / "libsrc").is_dir():
            continue
        source = cmake_source.read_text(encoding="utf-8")
        if "BSP_LIBSRC_SUBDIRS" not in source or "CMAKE_LIBRARY_PATH" not in source:
            continue
        library_dir = bsp_root / "lib"
        repaired = False
        if not library_dir.is_dir():
            library_dir.mkdir()
            repaired = True
            print(f"INFO: Restored BSP library directory: {library_dir}", flush=True)
        rsa_source = bsp_root / "libsrc/xilrsa/src"
        rsa_archive = rsa_source / "librsa.a"
        if (rsa_source / "CMakeLists.txt").is_file() and not rsa_archive.is_file():
            vendor_archive = installed_rsa_archive()
            shutil.copy2(vendor_archive, rsa_archive)
            repaired = True
            print(f"INFO: Restored vendor RSA input from active SDK: {vendor_archive}", flush=True)
        # Vendor CMake checks lib/../libsrc, which fails when lib is absent.
        # Touch only after repair so an existing build graph reconfigures and
        # discovers the previously skipped targets without discarding its cache.
        if repaired:
            cmake_source.touch()


def build_component(workspace: Path, component_name: str) -> None:
    if not workspace.is_dir():
        raise FileNotFoundError(f"Vitis workspace not found: {workspace}")
    metadata = workspace / component_name / "vitis-comp.json"
    if not metadata.is_file():
        raise FileNotFoundError(f"Vitis component not found: {metadata}")

    client = vitis.create_client()
    workspace_path = str(workspace.resolve())
    try:
        client.set_workspace(workspace_path)
    except Exception as error:
        # Portable archives contain components, not machine-local workspace metadata.
        # Recover only the vendor's explicit workspace-version initialization error.
        if "cannot recognize the workspace version" not in str(error).lower():
            raise
        print(f"INFO: Initializing Vitis workspace metadata: {workspace_path}", flush=True)
        client.update_workspace(path=workspace_path)
        client.set_workspace(workspace_path)
    component = client.get_component(name=component_name)
    if component is None:
        raise RuntimeError(
            f"Vitis did not discover component {component_name!r} in {workspace}"
        )
    prepare_bsp_output_directories(workspace / component_name)
    status = component.build()
    if status is False:
        raise RuntimeError(f"Vitis build failed for component {component_name!r}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build GPGPU Vitis components")
    subparsers = parser.add_subparsers(dest="action", required=True)
    build = subparsers.add_parser("build")
    build.add_argument("--workspace", type=Path, required=True)
    build.add_argument("--component", required=True)
    # The vendor launcher may forward its argument separator to the script.
    argv = sys.argv[1:]
    if argv[:1] == ["--"]:
        argv = argv[1:]
    arguments = parser.parse_args(argv)

    if arguments.action == "build":
        build_component(arguments.workspace, arguments.component)


if __name__ == "__main__":
    main()
