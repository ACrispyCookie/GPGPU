"""Resolved-configuration inspection commands."""

from __future__ import annotations

import json
from typing import Any

from rich.console import Console
import typer
import yaml

from ..config import ConfigError, ResolvedConfig, validate_config
from .common import display_path, plain, print_summary


app = typer.Typer(help="Inspect the fully resolved configuration.")


@app.command("show")
def show(
    ctx: typer.Context,
    output_format: str = typer.Option(
        "yaml", "--format", help="Output format: yaml or json."
    ),
) -> None:
    """Print the complete resolved configuration."""

    config: ResolvedConfig = ctx.obj
    values = config.to_dict()
    if output_format == "json":
        typer.echo(json.dumps(values, indent=2))
    elif output_format == "yaml":
        typer.echo(yaml.safe_dump(values, sort_keys=False), nl=False)
    else:
        raise typer.BadParameter("--format must be 'yaml' or 'json'")


@app.command("get")
def get(
    ctx: typer.Context,
    key: str = typer.Argument(..., help="Dotted configuration key."),
    source: bool = typer.Option(False, "--source", help="Also print the winning layer."),
) -> None:
    """Print one resolved value."""

    config: ResolvedConfig = ctx.obj
    try:
        value: Any = config.get(key)
    except ConfigError as exc:
        raise typer.BadParameter(str(exc)) from exc
    rendered = yaml.safe_dump(plain(value), sort_keys=False).strip()
    rendered = "\n".join(line for line in rendered.splitlines() if line != "...")
    typer.echo(rendered)
    if source:
        try:
            winning_source = config.source_of(key)
        except ConfigError as exc:
            raise typer.BadParameter(str(exc)) from exc
        typer.echo(f"source: {display_path(winning_source, config.repo_root)}")


@app.command("validate")
def validate(ctx: typer.Context) -> None:
    """Check that the resolved config satisfies the default-profile contract."""

    config: ResolvedConfig = ctx.obj
    console = Console()
    try:
        report = validate_config(config)
    except ConfigError as exc:
        print_summary(console, [str(exc)], [])
        raise typer.Exit(1) from exc
    print_summary(console, list(report.errors), list(report.warnings))
    if not report.valid:
        raise typer.Exit(1)
