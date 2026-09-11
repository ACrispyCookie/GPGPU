"""Shared presentation helpers for CLI commands."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from rich.console import Console


def print_summary(console: Console, errors: list[str], warnings: list[str]) -> None:
    if errors:
        console.print("\n[bold red]Errors[/bold red]")
        for error in errors:
            console.print(f"  [red]•[/red] {error}")
    if warnings:
        console.print("\n[bold yellow]Warnings[/bold yellow]")
        for warning in warnings:
            console.print(f"  [yellow]•[/yellow] {warning}")
    color = "red" if errors else "green"
    console.print(
        f"\n[bold {color}]Summary — Errors: {len(errors)} | "
        f"Warnings: {len(warnings)}[/bold {color}]"
    )


def display_path(path: str, root: Path) -> str:
    try:
        return str(Path(path).relative_to(root))
    except ValueError:
        return path


def plain(value: Any) -> Any:
    if hasattr(value, "items"):
        return {key: plain(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [plain(item) for item in value]
    return value
