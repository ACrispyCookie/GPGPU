"""Portable staged Vitis project, build, and export tasks."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath
from tempfile import NamedTemporaryFile, TemporaryDirectory
from typing import TYPE_CHECKING, Any
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile

from doit.tools import config_changed

if TYPE_CHECKING:
    from config import ResolvedConfig

from src.project_paths import ProjectPaths


_TEXT_SUFFIXES = {
    "",
    ".c",
    ".cmake",
    ".h",
    ".ini",
    ".json",
    ".ld",
    ".md",
    ".py",
    ".tcl",
    ".txt",
    ".yaml",
    ".yml",
}
_EXCLUDED_SUFFIXES = {
    ".a",
    ".bit",
    ".d",
    ".elf",
    ".log",
    ".o",
    ".obj",
    ".xsa",
}
_EXCLUDED_PARTS = {
    ".Xil",
    ".lock",
    ".vitisWorkspace.json",
    "__pycache__",
    "build",
    "build_configs",
    "CMakeFiles",
    "export",
    "logs",
}


def _string(config: ResolvedConfig, key: str) -> str:
    value = config.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{key} must be a non-empty string")
    return value


def _string_list(config: ResolvedConfig, key: str) -> tuple[str, ...]:
    value = config.get(key)
    if not isinstance(value, (list, tuple)) or not value:
        raise ValueError(f"{key} must be a non-empty list")
    result = tuple(value)
    if not all(isinstance(item, str) and item for item in result):
        raise ValueError(f"{key} must contain only non-empty strings")
    return result


def _safe_member_path(name: str) -> PurePosixPath:
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"Unsafe path in Vitis project archive: {name}")
    return path


def _replace_placeholders(path: Path, replacements: Mapping[str, str]) -> None:
    if path.suffix.lower() not in _TEXT_SUFFIXES:
        return
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return
    updated = text
    for marker, value in replacements.items():
        updated = updated.replace(marker, value)
    if updated != text:
        path.write_text(updated, encoding="utf-8")


def _validate_component_metadata(path: Path, expected_name: str) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"Missing Vitis component metadata: {path}")
    try:
        metadata = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise ValueError(f"Invalid Vitis component metadata: {path}") from exc
    if not isinstance(metadata, dict) or metadata.get("name") != expected_name:
        raise ValueError(f"Vitis component at {path} is not named {expected_name!r}")
    return metadata


def _apply_config_contract(
    platform_metadata: Mapping[str, Any],
    host_metadata: Mapping[str, Any],
    host_root: Path,
    cpu: str,
    domain: str,
    os_name: str,
    template: str,
    host_sources: Sequence[Path],
) -> None:
    expected_host = {"cpuInstance": cpu, "domain": domain, "os": os_name}
    mismatches = [
        f"{key}={host_metadata.get(key)!r} (configured {value!r})"
        for key, value in expected_host.items()
        if host_metadata.get(key) != value
    ]
    platform_configuration = platform_metadata.get("configuration")
    domains = (
        platform_configuration.get("domains", [])
        if isinstance(platform_configuration, Mapping)
        else []
    )
    matching_domain = next(
        (item for item in domains if isinstance(item, Mapping) and item.get("name") == domain),
        None,
    )
    if matching_domain is None:
        mismatches.append(f"platform domain {domain!r} is missing")
    else:
        for key, value in (("processor", cpu), ("os", os_name), ("appTemplate", template)):
            if matching_domain.get(key) != value:
                mismatches.append(
                    f"domain.{key}={matching_domain.get(key)!r} (configured {value!r})"
                )

    app_yaml = host_root / "src/app.yaml"
    app_yaml_text = app_yaml.read_text(encoding="utf-8") if app_yaml.is_file() else ""
    if not re.search(
        rf"(?m)^template:\s*{re.escape(template)}\s*$",
        app_yaml_text,
    ):
        mismatches.append(f"host template {template!r} is missing from {app_yaml}")
    if mismatches:
        raise ValueError(
            "Vitis default project does not match hardware.vitis configuration: "
            + "; ".join(mismatches)
        )

    user_config = host_root / "src/UserConfig.cmake"
    text = user_config.read_text(encoding="utf-8")
    source_block = "set(USER_COMPILE_SOURCES\n" + "".join(
        f'"{source.resolve()}"\n' for source in host_sources
    ) + ")"
    updated, count = re.subn(
        r"set\(USER_COMPILE_SOURCES\s*.*?\n\)",
        source_block,
        text,
        count=1,
        flags=re.DOTALL,
    )
    if count != 1:
        raise ValueError(f"Unable to update USER_COMPILE_SOURCES in {user_config}")
    user_config.write_text(updated, encoding="utf-8")


def materialize_default_project(
    archive: Path,
    workspace: Path,
    repo_root: Path,
    xsa: Path,
    platform_name: str,
    host_name: str,
    cpu: str,
    domain: str,
    os_name: str,
    template: str,
    host_sources: Sequence[Path],
) -> None:
    """Extract the committed portable default into the editable build workspace."""

    archive = archive.resolve()
    workspace = workspace.resolve()
    repo_root = repo_root.resolve()
    xsa = xsa.resolve()
    if not archive.is_file():
        raise FileNotFoundError(f"Default Vitis project archive not found: {archive}")
    if not xsa.is_file():
        raise FileNotFoundError(f"Vivado XSA not found: {xsa}")

    component_roots = (workspace / platform_name, workspace / host_name)
    existing = [path for path in component_roots if path.exists()]
    if existing:
        if len(existing) != len(component_roots):
            joined = ", ".join(str(path) for path in existing)
            raise FileExistsError(
                "Vitis workspace contains only part of the expected component state: "
                f"{joined}. Restore both components or remove the incomplete workspace."
            )
        for component_root in component_roots:
            if component_root.is_symlink():
                raise ValueError(
                    f"Refusing to refresh symbolic-link component: {component_root}"
                )

        platform_metadata_path = component_roots[0] / "vitis-comp.json"
        host_metadata_path = component_roots[1] / "vitis-comp.json"
        platform_metadata = _validate_component_metadata(
            platform_metadata_path, platform_name
        )
        host_metadata = _validate_component_metadata(host_metadata_path, host_name)
        _apply_config_contract(
            platform_metadata,
            host_metadata,
            component_roots[1],
            cpu,
            domain,
            os_name,
            template,
            host_sources,
        )

        configuration = platform_metadata.get("configuration")
        if not isinstance(configuration, dict):
            raise ValueError(
                f"Platform metadata has no configuration mapping: {platform_metadata_path}"
            )
        configuration["xsa"] = str(xsa)
        configuration["xsaPathInPlatform"] = (
            f"{platform_name}/hw/{platform_name}.xsa"
        )
        metadata_temporary = platform_metadata_path.with_suffix(".json.tmp")
        metadata_temporary.write_text(
            json.dumps(platform_metadata, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        metadata_temporary.replace(platform_metadata_path)

        embedded_xsa = component_roots[0] / "hw" / f"{platform_name}.xsa"
        embedded_xsa.parent.mkdir(parents=True, exist_ok=True)
        xsa_temporary = embedded_xsa.with_suffix(".xsa.tmp")
        shutil.copy2(xsa, xsa_temporary)
        xsa_temporary.replace(embedded_xsa)
        return

    workspace.parent.mkdir(parents=True, exist_ok=True)
    allowed_roots = {platform_name, host_name}
    with TemporaryDirectory(prefix=".vitis-project-", dir=workspace.parent) as temporary:
        staging = Path(temporary)
        with zipfile.ZipFile(archive) as source:
            for member in source.infolist():
                relative = _safe_member_path(member.filename)
                if not relative.parts or relative.parts[0] not in allowed_roots:
                    continue
                destination = staging.joinpath(*relative.parts)
                if member.is_dir():
                    destination.mkdir(parents=True, exist_ok=True)
                    continue
                destination.parent.mkdir(parents=True, exist_ok=True)
                with source.open(member) as input_file, destination.open("wb") as output_file:
                    shutil.copyfileobj(input_file, output_file)

        staged_roots = (staging / platform_name, staging / host_name)
        platform_metadata_path = staged_roots[0] / "vitis-comp.json"
        host_metadata_path = staged_roots[1] / "vitis-comp.json"
        platform_metadata = _validate_component_metadata(platform_metadata_path, platform_name)
        host_metadata = _validate_component_metadata(host_metadata_path, host_name)
        _apply_config_contract(
            platform_metadata,
            host_metadata,
            staged_roots[1],
            cpu,
            domain,
            os_name,
            template,
            host_sources,
        )

        configuration = platform_metadata.get("configuration")
        if not isinstance(configuration, dict):
            raise ValueError(
                f"Platform metadata has no configuration mapping: {platform_metadata_path}"
            )
        configuration["xsa"] = str(xsa)
        configuration["xsaPathInPlatform"] = f"{platform_name}/hw/{platform_name}.xsa"
        platform_metadata_path.write_text(
            json.dumps(platform_metadata, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

        replacements = {
            "${GPGPU_REPO_ROOT}": str(repo_root),
            "${GPGPU_WORKSPACE}": str(workspace),
            "${GPGPU_XSA}": str(xsa),
        }
        for component_root in staged_roots:
            for path in component_root.rglob("*"):
                if path.is_file():
                    _replace_placeholders(path, replacements)

        embedded_xsa = staged_roots[0] / "hw" / f"{platform_name}.xsa"
        embedded_xsa.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(xsa, embedded_xsa)

        workspace.mkdir(parents=True, exist_ok=True)
        for staged_root, component_root in zip(staged_roots, component_roots, strict=True):
            os.replace(staged_root, component_root)


def _portable_text(
    text: str,
    repo_root: Path,
    workspace: Path,
    xsa: Path,
    vendor_root: str | None,
) -> str:
    replacements = [
        (str(xsa.resolve()), "${GPGPU_XSA}"),
        (str(workspace.resolve()), "${GPGPU_WORKSPACE}"),
        (str(repo_root.resolve()), "${GPGPU_REPO_ROOT}"),
    ]
    if vendor_root:
        vendor_path = Path(vendor_root)
        replacements.extend(
            (
                (str(vendor_path), "${XILINX_VITIS}"),
                (str(vendor_path.parent), "${XILINX_VITIS}/.."),
            )
        )
    replacements.sort(key=lambda item: len(item[0]), reverse=True)
    result = text
    for absolute, marker in replacements:
        result = result.replace(absolute, marker)
    return result


def _vitis_vendor_root(host_root: Path) -> str | None:
    app_yaml = host_root / "src/app.yaml"
    if not app_yaml.is_file():
        return None
    match = re.search(
        r"(?m)^app_src_dir:\s*(.+?)/data/embeddedsw(?:/|$)",
        app_yaml.read_text(encoding="utf-8"),
    )
    if match is None or match.group(1).startswith("${"):
        return None
    return match.group(1)


def _archive_excluded(relative: Path, platform_name: str) -> bool:
    if any(part in _EXCLUDED_PARTS for part in relative.parts):
        return True
    if relative.suffix.lower() in _EXCLUDED_SUFFIXES:
        return True
    if relative.parts[:1] == ("hw",) and relative.name == f"{platform_name}.xsa":
        return True
    return False


def _write_portable_entry(output: zipfile.ZipFile, name: str, data: bytes) -> None:
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o100644 << 16
    output.writestr(info, data, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)


def _mark_workspace_exported(workspace: Path, component_names: Sequence[str]) -> None:
    for component_name in component_names:
        (workspace / component_name / "vitis-comp.json").touch()


def export_workspace(
    workspace: Path,
    archive: Path,
    repo_root: Path,
    platform_name: str,
    host_name: str,
) -> None:
    """Atomically synchronize the editable workspace into a portable archive."""

    workspace = workspace.resolve()
    repo_root = repo_root.resolve()
    archive = archive.resolve()
    platform_root = workspace / platform_name
    host_root = workspace / host_name
    for component_root in (platform_root, host_root):
        if component_root.is_symlink():
            raise ValueError(f"Refusing to export symbolic link: {component_root}")
    platform_metadata_path = platform_root / "vitis-comp.json"
    host_metadata_path = host_root / "vitis-comp.json"
    platform_metadata = _validate_component_metadata(platform_metadata_path, platform_name)
    _validate_component_metadata(host_metadata_path, host_name)
    vendor_root = _vitis_vendor_root(host_root)

    configuration = platform_metadata.get("configuration")
    if not isinstance(configuration, dict):
        raise ValueError(
            f"Platform metadata has no configuration mapping: {platform_metadata_path}"
        )
    xsa_value = configuration.get("xsa")
    xsa = Path(xsa_value) if isinstance(xsa_value, str) and xsa_value else repo_root / "missing.xsa"

    archive.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(
        prefix=f".{archive.name}.", suffix=".tmp", dir=archive.parent, delete=False
    ) as temporary:
        temporary_path = Path(temporary.name)

    try:
        with zipfile.ZipFile(
            temporary_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
        ) as output:
            for component_name, component_root in (
                (platform_name, platform_root),
                (host_name, host_root),
            ):
                for path in sorted(component_root.rglob("*")):
                    if path.is_symlink():
                        raise ValueError(f"Refusing to export symbolic link: {path}")
                    if not path.is_file():
                        continue
                    relative = path.relative_to(component_root)
                    if _archive_excluded(relative, platform_name):
                        continue
                    archive_name = (Path(component_name) / relative).as_posix()
                    data = path.read_bytes()
                    if path.suffix.lower() in _TEXT_SUFFIXES:
                        try:
                            text = data.decode("utf-8")
                        except UnicodeDecodeError:
                            pass
                        else:
                            if path == platform_metadata_path:
                                metadata = json.loads(text)
                                metadata["configuration"]["xsa"] = "${GPGPU_XSA}"
                                metadata["configuration"][
                                    "xsaPathInPlatform"
                                ] = f"{platform_name}/hw/{platform_name}.xsa"
                                text = json.dumps(
                                    metadata, indent=2, ensure_ascii=False
                                ) + "\n"
                            data = _portable_text(
                                text, repo_root, workspace, xsa, vendor_root
                            ).encode("utf-8")
                    _write_portable_entry(output, archive_name, data)

        with zipfile.ZipFile(temporary_path) as check:
            names = set(check.namelist())
            required = {
                f"{platform_name}/vitis-comp.json",
                f"{host_name}/vitis-comp.json",
            }
            missing = required - names
            if missing:
                raise ValueError(
                    "Portable Vitis archive is missing: " + ", ".join(sorted(missing))
                )
            for name in names:
                raw = check.read(name)
                lowered = raw.lower()
                if (
                    b"/home/" in lowered
                    or b"/workspace/" in lowered
                    or b"tsiantosd" in lowered
                ):
                    raise ValueError(
                        f"Refusing to export machine-specific path data in {name}"
                    )
                try:
                    text = raw.decode("utf-8")
                except UnicodeDecodeError:
                    continue
                if "/home/" in text or "/workspace/" in text:
                    raise ValueError(
                        f"Refusing to export machine-specific absolute path in {name}"
                    )
        if archive.is_file() and archive.read_bytes() == temporary_path.read_bytes():
            temporary_path.unlink()
            _mark_workspace_exported(workspace, (platform_name, host_name))
            print(f"Portable Vitis default project is already current: {archive}", file=sys.stderr)
            return
        os.replace(temporary_path, archive)
        _mark_workspace_exported(workspace, (platform_name, host_name))
    finally:
        temporary_path.unlink(missing_ok=True)

    print(f"Updated portable Vitis default project: {archive}", file=sys.stderr)


def run_vitis(
    command: Sequence[str], repo_root: Path, expected_outputs: Sequence[Path]
) -> None:
    subprocess.run(list(command), cwd=repo_root, check=True)
    missing = [str(path) for path in expected_outputs if not path.is_file()]
    if missing:
        raise FileNotFoundError(
            "Vitis completed without producing required artifacts: " + ", ".join(missing)
        )


def create_tasks(config: ResolvedConfig) -> list[dict[str, Any]]:
    paths = ProjectPaths.from_config(config)
    repo_root = paths.repo_root
    workspace = paths.software_build / "vitis"
    platform_name = _string(config, "hardware.vitis.platform_name")
    host_name = _string(config, "hardware.vitis.host_name")
    cpu = _string(config, "hardware.vitis.cpu")
    domain = _string(config, "hardware.vitis.domain")
    os_name = _string(config, "hardware.vitis.os")
    template = _string(config, "hardware.vitis.template")
    default_archive = repo_root / _string(config, "hardware.vitis.default_archive")
    host_sources = tuple(
        repo_root / relative for relative in _string_list(config, "hardware.vitis.host_sources")
    )
    vitis_command = _string(config, "tools.vitis.command")
    flow_script = repo_root / "tools/hardware/vitis/vitis_flow.py"
    xsa = paths.platform / f"{platform_name}.xsa"

    platform_root = workspace / platform_name
    host_root = workspace / host_name
    platform_metadata = platform_root / "vitis-comp.json"
    host_metadata = host_root / "vitis-comp.json"
    platform_xsa = (
        platform_root / f"export/{platform_name}/hw/{platform_name}.xsa"
    )
    ps_init = platform_root / f"export/{platform_name}/hw/sdt/ps7_init.tcl"
    platform_xpfm = platform_root / f"export/{platform_name}/{platform_name}.xpfm"
    host_elf = host_root / f"build/{host_name}.elf"

    def build_command(component: str) -> list[str]:
        return [
            vitis_command,
            "-s",
            str(flow_script),
            "--",
            "build",
            "--workspace",
            str(workspace),
            "--component",
            component,
        ]

    platform_command = build_command(platform_name)
    host_command = build_command(host_name)

    return [
        {
            "name": "vitis:project",
            "actions": [
                (
                    materialize_default_project,
                    [
                        default_archive,
                        workspace,
                        repo_root,
                        xsa,
                        platform_name,
                        host_name,
                        cpu,
                        domain,
                        os_name,
                        template,
                        host_sources,
                    ],
                )
            ],
            "task_dep": [] if xsa.is_file() else ["vivado:xsa"],
            "file_dep": [
                str(default_archive),
                str(xsa),
                str(flow_script),
                *(str(path) for path in host_sources),
            ],
            "targets": [str(platform_metadata), str(host_metadata)],
            "uptodate": [
                config_changed(
                    {
                        "version": _string(config, "hardware.vitis.version"),
                        "platform": platform_name,
                        "host": host_name,
                        "cpu": cpu,
                        "domain": domain,
                        "os": os_name,
                        "template": template,
                        "sources": [str(path) for path in host_sources],
                    }
                )
            ],
        },
        {
            "name": "vitis:build:platform",
            "actions": [
                (
                    run_vitis,
                    [platform_command, repo_root, (platform_xsa, ps_init, platform_xpfm)],
                )
            ],
            "task_dep": ["vitis:project"],
            "file_dep": [str(flow_script), str(platform_metadata), str(xsa)],
            "targets": [str(platform_xsa), str(ps_init), str(platform_xpfm)],
            "uptodate": [config_changed({"command": platform_command})],
            "clean": True,
        },
        {
            "name": "vitis:build:host",
            "actions": [(run_vitis, [host_command, repo_root, (host_elf,)])],
            "task_dep": ["vitis:build:platform"],
            "file_dep": [
                str(flow_script),
                str(host_metadata),
                str(platform_xsa),
                str(ps_init),
                str(platform_xpfm),
                *(str(path) for path in host_sources),
            ],
            "targets": [str(host_elf)],
            "uptodate": [config_changed({"command": host_command})],
            "clean": True,
        },
        {
            "name": "vitis:build:all",
            "actions": None,
            "task_dep": ["vitis:build:host"],
        },
        {
            "name": "vitis:export",
            "actions": [
                (
                    export_workspace,
                    [workspace, default_archive, repo_root, platform_name, host_name],
                )
            ],
            "uptodate": [False],
        },
    ]
