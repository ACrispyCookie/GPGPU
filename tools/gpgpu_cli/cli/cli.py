"""Typer application construction and global configuration resolution."""

from __future__ import annotations

from pathlib import Path

import typer

from .commands.config import app as config_app
from .commands.doctor import doctor
from .config import ConfigError, resolve_config
from .paths import RepoNotFoundError, find_repo_root


def create_app(*, repo_root: str | Path | None = None) -> typer.Typer:
    """Create the CLI application, optionally pinned to a root for tests."""

    app = typer.Typer(
        name="gpgpu",
        help="Build, test, and operate the ECE338 GPGPU project.",
        no_args_is_help=True,
        add_completion=True,
        rich_markup_mode="rich",
    )
    app.add_typer(config_app, name="config")
    app.command()(doctor)

    def root() -> Path:
        return Path(repo_root).resolve() if repo_root is not None else find_repo_root()

    @app.callback()
    def callback(
        ctx: typer.Context,
        profile: str = typer.Option(
            "default", "--profile", "-p", help="Profile from config/profiles."
        ),
        set_values: list[str] | None = typer.Option(
            None,
            "--set",
            metavar="OPTION=VALUE",
            help="Override a known option; repeat for multiple values.",
        ),
    ) -> None:
        """Resolve configuration once, before dispatching a command."""

        try:
            repository = root()
            ctx.obj = resolve_config(
                repository,
                profile=profile,
                overrides=set_values or (),
            )
        except (RepoNotFoundError, ConfigError) as exc:
            raise typer.BadParameter(str(exc)) from exc

    return app


def main() -> None:
    create_app()()


if __name__ == "__main__":
    main()
