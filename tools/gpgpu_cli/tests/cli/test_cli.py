from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from cli.cli import create_app


runner = CliRunner()


def make_repo(tmp_path: Path) -> Path:
    profiles = tmp_path / "config/profiles"
    profiles.mkdir(parents=True)
    (profiles / "default.yaml").write_text(
        """
project:
  name: test-gpgpu
paths:
  build: build
tools:
  python:
    command: python3
    required: true
  optional_missing:
    command: command-that-does-not-exist-gpgpu-test
    required: false
""",
        encoding="utf-8",
    )
    return tmp_path


def test_config_show_uses_global_profile_and_cli_overrides(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    app = create_app(repo_root=repo)

    result = runner.invoke(
        app,
        ["--profile", "default", "--set", "project.name=overridden", "config", "show", "--format", "json"],
    )

    assert result.exit_code == 0, result.output
    document = json.loads(result.stdout)
    assert document["project"]["name"] == "overridden"


def test_config_get_reports_value_and_source(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    app = create_app(repo_root=repo)

    result = runner.invoke(app, ["config", "get", "project.name", "--source"])

    assert result.exit_code == 0, result.output
    assert result.stdout.splitlines()[0] == "test-gpgpu"
    assert "..." not in result.stdout
    assert "config/profiles/default.yaml" in result.stdout


def test_doctor_distinguishes_required_and_optional_tools(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    app = create_app(repo_root=repo)

    result = runner.invoke(app, ["doctor"])

    assert result.exit_code == 0, result.output
    assert "python" in result.stdout
    assert "optional_missing" in result.stdout
    assert "MISSING (optional)" in result.stdout
    assert "Errors: 0" in result.stdout
    assert "Warnings: 1" in result.stdout


def test_config_validate_accepts_partial_profile_inheriting_default(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    (repo / "config/profiles/incomplete.yaml").write_text(
        "project:\n  name: incomplete\n",
        encoding="utf-8",
    )
    app = create_app(repo_root=repo)

    result = runner.invoke(app, ["--profile", "incomplete", "config", "validate"])

    assert result.exit_code == 0, result.output
    assert "Errors: 0" in result.stdout


def test_doctor_does_not_duplicate_config_structure_errors(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    (repo / "config/local.yaml").write_text("tools: invalid\n", encoding="utf-8")
    app = create_app(repo_root=repo)

    result = runner.invoke(app, ["doctor"])

    assert result.exit_code == 1, result.output
    assert result.stdout.count("tools must be a mapping") == 1
    assert "The 'tools' configuration option must be a mapping" not in result.stdout
    assert "Errors: 1" in result.stdout


def test_callback_fails_immediately_on_config_parse_error(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    (repo / "config/profiles/broken.yaml").write_text("project: [\n", encoding="utf-8")
    app = create_app(repo_root=repo)

    result = runner.invoke(app, ["--profile", "broken", "doctor"])

    assert result.exit_code == 2, result.output
    assert "Invalid YAML" in result.stderr
    assert "GPGPU environment" not in result.stdout
    assert "Summary" not in result.stdout


def test_doctor_counts_missing_required_repository_paths_as_errors(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    profile = repo / "config/profiles/default.yaml"
    profile.write_text(
        profile.read_text(encoding="utf-8")
        + "\npaths:\n  build: build\n  hardware:\n    rtl: missing-rtl\n",
        encoding="utf-8",
    )
    app = create_app(repo_root=repo)

    result = runner.invoke(app, ["doctor"])

    assert result.exit_code == 1, result.output
    assert "Repository path is missing: paths.hardware.rtl" in result.stdout
    assert "Errors: 1" in result.stdout


def test_help_exposes_core_commands_and_completion_flags(tmp_path: Path) -> None:
    app = create_app(repo_root=make_repo(tmp_path))

    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0, result.output
    assert "init" not in result.stdout
    assert "doctor" in result.stdout
    assert "config" in result.stdout
    assert "--install-completion" in result.stdout
    assert "--show-completion" in result.stdout


def test_command_handlers_live_in_commands_package() -> None:
    package = Path(__file__).resolve().parents[2] / "cli"
    entrypoint = (package / "cli.py").read_text(encoding="utf-8")

    assert (package / "commands/__init__.py").is_file()
    assert (package / "commands/doctor.py").is_file()
    assert (package / "commands/config.py").is_file()
    assert "def doctor(" not in entrypoint
    assert "def config_show(" not in entrypoint
    assert "def config_get(" not in entrypoint
    assert "def config_validate(" not in entrypoint
