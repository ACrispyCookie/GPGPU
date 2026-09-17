"""Repository discovery and recursive configured-path resolution."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
import subprocess
from types import MappingProxyType
from typing import Any


class RepoNotFoundError(RuntimeError):
    """Raised when a GPGPU repository root cannot be located."""


class PathResolutionError(ValueError):
    """Raised when the configured path tree has an invalid shape or key."""


def _append_path(base: Path, raw: str) -> Path:
    component = Path(raw).expanduser()
    return (component if component.is_absolute() else base / component).resolve()


def resolve_repo_paths(repo_root: Path, configured: object) -> Mapping[str, Path]:
    """Resolve all entries in ``paths``, accumulating nested section roots."""

    if not isinstance(configured, Mapping):
        raise PathResolutionError("paths must be a mapping")

    resolved: dict[str, Path] = {}

    def walk(section: Mapping[str, Any], base: Path, prefix: str) -> None:
        for key, value in section.items():
            dotted = f"{prefix}.{key}"
            if isinstance(value, str):
                resolved[dotted] = _append_path(base, value)
                continue
            if not isinstance(value, Mapping):
                raise PathResolutionError(f"{dotted} must be a string or mapping")

            root = value.get("root")
            if not isinstance(root, str):
                raise PathResolutionError(f"{dotted} must define a string root")
            section_base = _append_path(base, root)
            resolved[f"{dotted}.root"] = section_base
            children = {child: item for child, item in value.items() if child != "root"}
            walk(children, section_base, dotted)

    walk(configured, repo_root, "paths")
    return MappingProxyType(resolved)


def resolve_repo_path(repo_root: Path, configured: object, dotted_key: str) -> Path:
    """Resolve one dotted key from the configured ``paths`` tree."""

    paths = resolve_repo_paths(repo_root, configured)
    try:
        return paths[dotted_key]
    except KeyError as exc:
        raise PathResolutionError(f"Unknown path configuration option: {dotted_key}") from exc


def find_repo_root(start: str | Path | None = None) -> Path:
    """Find the enclosing repository containing the GPGPU profile directory."""

    start_path = Path(start or Path.cwd()).resolve()
    directory = start_path if start_path.is_dir() else start_path.parent
    try:
        result = subprocess.run(
            ["git", "-C", str(directory), "rev-parse", "--show-toplevel"],
            check=True,
            capture_output=True,
            text=True,
        )
        candidate = Path(result.stdout.strip()).resolve()
        if (candidate / "config/profiles").is_dir():
            return candidate
    except (FileNotFoundError, subprocess.CalledProcessError):
        pass

    for candidate in (directory, *directory.parents):
        if (candidate / "config/profiles").is_dir():
            return candidate
    raise RepoNotFoundError(f"Could not find a GPGPU repository from {start_path}")
