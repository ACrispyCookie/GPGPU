from __future__ import annotations

from pathlib import Path

import pytest

from cli.config import ConfigError, resolve_config, validate_config


def write_yaml(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def make_repo(tmp_path: Path) -> Path:
    write_yaml(
        tmp_path / "config/profiles/default.yaml",
        """
architecture:
  cores: 32
tools:
  make:
    command: make
    required: true
paths:
  build: build
nested:
  keep: profile
  replace: profile
""",
    )
    write_yaml(
        tmp_path / "config/local.yaml",
        """
nested:
  replace: local
local_only: true
""",
    )
    return tmp_path


def test_resolution_order_profile_then_local_then_cli(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)

    resolved = resolve_config(
        repo,
        profile="default",
        overrides=["architecture.cores=64", "nested.replace=cli"],
    )

    assert resolved.profile == "default"
    assert resolved.get("architecture.cores") == 64
    assert resolved.get("nested.keep") == "profile"
    assert resolved.get("nested.replace") == "cli"
    assert resolved.get("local_only") is True
    assert resolved.source_of("architecture.cores") == "cli"
    assert resolved.source_of("nested.keep").endswith("config/profiles/default.yaml")
    assert resolved.source_of("local_only").endswith("config/local.yaml")


def test_resolved_config_is_deeply_immutable(tmp_path: Path) -> None:
    resolved = resolve_config(make_repo(tmp_path), profile="default")

    with pytest.raises(TypeError):
        resolved.values["architecture"] = {}  # type: ignore[index]
    with pytest.raises(TypeError):
        resolved.values["architecture"]["cores"] = 1  # type: ignore[index]


def test_cli_override_parses_yaml_scalars_and_collections(tmp_path: Path) -> None:
    resolved = resolve_config(
        make_repo(tmp_path),
        profile="default",
        overrides=["architecture.cores=16", "local_only=false", "nested.items=[a, b]"],
        allow_new_keys=True,
    )

    assert resolved.get("architecture.cores") == 16
    assert resolved.get("local_only") is False
    assert resolved.get("nested.items") == ("a", "b")


def test_unknown_cli_override_is_rejected_by_default(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="Unknown configuration option"):
        resolve_config(make_repo(tmp_path), profile="default", overrides=["typo.value=1"])


def test_missing_and_invalid_profiles_fail_clearly(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)

    with pytest.raises(ConfigError, match="Profile not found"):
        resolve_config(repo, profile="missing")
    with pytest.raises(ConfigError, match="Invalid profile name"):
        resolve_config(repo, profile="../outside")


def test_repo_path_resolves_relative_paths_against_repository(tmp_path: Path) -> None:
    resolved = resolve_config(make_repo(tmp_path), profile="default")

    assert resolved.repo_path("paths.build") == (tmp_path / "build").resolve()


def test_selected_profile_inherits_default_options_before_cli_overrides(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    write_yaml(
        repo / "config/profiles/incomplete.yaml",
        """
architecture:
  cores: 16
tools:
  make:
    command: make
    required: true
""",
    )

    resolved = resolve_config(
        repo,
        profile="incomplete",
        overrides=["paths.build=custom-build"],
    )
    report = validate_config(resolved)

    assert resolved.get("architecture.cores") == 16
    assert resolved.get("nested.keep") == "profile"
    assert resolved.get("paths.build") == "custom-build"
    assert resolved.source_of("nested.keep").endswith("config/profiles/default.yaml")
    assert resolved.source_of("architecture.cores").endswith(
        "config/profiles/incomplete.yaml"
    )
    assert resolved.source_of("paths.build") == "cli"
    assert report.valid


def test_validation_warns_about_options_not_declared_by_default_profile(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    write_yaml(repo / "config/local.yaml", "unexpected:\n  option: true\n")

    report = validate_config(resolve_config(repo))

    assert report.valid
    assert any("unexpected.option" in warning for warning in report.warnings)
