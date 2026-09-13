"""Repository discovery for the GPGPU command-line interface."""

from __future__ import annotations

from pathlib import Path
import subprocess


class RepoNotFoundError(RuntimeError):
    """Raised when a GPGPU repository root cannot be located."""


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
