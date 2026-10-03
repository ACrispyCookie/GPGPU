"""Repository discovery and single build-root resolution."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
import subprocess


class RepoNotFoundError(RuntimeError):
    """Raised when a GPGPU repository root cannot be located."""


class PathResolutionError(ValueError):
    """Raised when the configured path tree has an invalid shape or key."""


_PROTECTED_REPOSITORY_DIRECTORIES = (
    ".git",
    "config",
    "demo",
    "docs",
    "hardware",
    "software",
    "tests",
    "tools",
)


def _append_path(base: Path, raw: str) -> Path:
    component = Path(raw).expanduser()
    return (component if component.is_absolute() else base / component).resolve()


def _contains(parent: Path, child: Path) -> bool:
    return parent == child or parent in child.parents


def _validate_build_root(repo_root: Path, build_root: Path) -> None:
    repository = repo_root.resolve()
    if _contains(build_root, repository):
        raise PathResolutionError(
            "paths.build.root must not be the repository root or one of its ancestors"
        )

    for relative in _PROTECTED_REPOSITORY_DIRECTORIES:
        protected = repository / relative
        if _contains(protected, build_root) or _contains(build_root, protected):
            raise PathResolutionError(
                "paths.build.root overlaps protected repository directory: "
                f"{protected}"
            )


def resolve_build_root(repo_root: Path, configured: object) -> Path:
    """Resolve the sole configurable path: ``paths.build.root``."""

    if not isinstance(configured, Mapping):
        raise PathResolutionError("paths must be a mapping")
    build = configured.get("build")
    if not isinstance(build, Mapping):
        raise PathResolutionError("paths.build must be a mapping")
    raw = build.get("root")
    if not isinstance(raw, str) or not raw:
        raise PathResolutionError("paths.build.root must be a non-empty string")
    resolved = _append_path(repo_root, raw)
    _validate_build_root(repo_root, resolved)
    return resolved


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
