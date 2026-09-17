"""Execute one pydoit task from the resolved project graph."""

from __future__ import annotations

import typer

from config import ResolvedConfig
from src import run as run_doit


def run(ctx: typer.Context, task: str = typer.Argument(..., help="pydoit task name.")) -> None:
    """Run one task from the GPGPU build graph."""

    config: ResolvedConfig = ctx.obj
    status = run_doit(config, ["run", task])
    if status:
        raise typer.Exit(status)
