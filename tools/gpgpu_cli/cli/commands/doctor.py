"""Environment diagnostic command."""

from __future__ import annotations

from pathlib import Path
import shutil

from rich.console import Console
from rich.table import Table
import typer

from config import ConfigError, ResolvedConfig, validate_config
from src.project_paths import ProjectPaths
from .common import display_path, print_summary


def doctor(ctx: typer.Context) -> None:
    """Check configured tools and repository paths."""

    config: ResolvedConfig = ctx.obj
    console = Console()
    errors: list[str] = []
    warnings: list[str] = []

    try:
        validation = validate_config(config)
    except ConfigError as exc:
        errors.append(str(exc))
        config_valid = False
    else:
        errors.extend(validation.errors)
        warnings.extend(validation.warnings)
        config_valid = validation.valid

    table = Table(title="GPGPU environment")
    table.add_column("Tool")
    table.add_column("Configured command")
    table.add_column("Status")
    table.add_row(
        "configuration",
        config.profile,
        "[green]VALID[/green]" if config_valid else "[red]INVALID[/red]",
    )

    tools = config.get("tools", {})
    if not hasattr(tools, "items"):
        tools = {}
    for name, specification in tools.items():
        if not hasattr(specification, "get"):
            continue
        command = specification.get("command")
        required = specification.get("required", False)
        if not isinstance(command, str) or not isinstance(required, bool):
            continue

        configured = Path(command).expanduser()
        if "/" in command:
            if not configured.is_absolute():
                configured = config.repo_root / configured
            found = str(configured.resolve()) if configured.exists() else None
        else:
            found = shutil.which(command)

        if found:
            status = f"[green]OK[/green] ({found})"
        elif required:
            errors.append(f"Required tool is missing: {name} ({command})")
            status = "[red]MISSING (required)[/red]"
        else:
            warnings.append(f"Optional tool is missing: {name} ({command})")
            status = "[yellow]MISSING (optional)[/yellow]"
        table.add_row(str(name), command, status)

    try:
        paths = ProjectPaths.from_config(config)
    except (ConfigError, ValueError) as exc:
        errors.append(str(exc))
    else:
        for key, path in paths.required_repository_paths().items():
            if path.is_dir():
                status = "[green]OK[/green]"
            elif path.exists():
                status = "[red]NOT A DIRECTORY[/red]"
                errors.append(f"Repository path is not a directory: {key} ({path})")
            else:
                status = "[red]MISSING[/red]"
                errors.append(f"Repository path is missing: {key} ({path})")
            table.add_row(key, display_path(str(path), config.repo_root), status)
        if paths.build_root.is_dir():
            build_status = "[green]OK[/green]"
        elif paths.build_root.exists():
            build_status = "[red]NOT A DIRECTORY[/red]"
            errors.append(f"Build root is not a directory: {paths.build_root}")
        else:
            build_status = "[blue]NOT BUILT[/blue]"
        table.add_row(
            "paths.build.root",
            display_path(str(paths.build_root), config.repo_root),
            build_status,
        )

    console.print(table)
    print_summary(console, errors, warnings)
    if errors:
        raise typer.Exit(1)
