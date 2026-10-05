from __future__ import annotations

from pathlib import Path

from src.project_paths import ProjectPaths


class StubResolvedConfig:
    def __init__(self, repo_root: Path, build_root: Path) -> None:
        self.repo_root = repo_root
        self.build_root = build_root


def test_project_paths_derive_fixed_sources_and_all_build_subdirectories(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "checkout"
    build = tmp_path / "external-build"

    paths = ProjectPaths.from_config(StubResolvedConfig(repo, build))

    assert paths.repo_root == repo.resolve()
    assert paths.config == repo.resolve() / "config"
    assert paths.hardware_rtl == repo.resolve() / "hardware/rtl"
    assert paths.hardware_constraints == repo.resolve() / "hardware/constraints"
    assert paths.software_host == repo.resolve() / "software/host"
    assert paths.software_programs == repo.resolve() / "software/programs"
    assert paths.rtl_tests == repo.resolve() / "tests/hardware/rtl"
    assert paths.demo == repo.resolve() / "demo"

    assert paths.build_root == build.resolve()
    assert paths.vivado == build.resolve() / "hardware/vivado"
    assert paths.hardware_reports == build.resolve() / "hardware/reports"
    assert paths.bitstream == build.resolve() / "hardware/bitstream"
    assert paths.platform == build.resolve() / "hardware/platform"
    assert paths.software_build == build.resolve() / "software"
    assert paths.vitis == build.resolve() / "software/vitis"
    assert paths.program_builds == build.resolve() / "software/programs"
    assert paths.rtl_test_build == build.resolve() / "tests/rtl"


def test_required_repository_paths_exclude_generated_build_tree(tmp_path: Path) -> None:
    paths = ProjectPaths.from_config(StubResolvedConfig(tmp_path, tmp_path / "build"))

    required = paths.required_repository_paths()

    assert "repository.hardware.rtl" in required
    assert "repository.software.programs" in required
    assert paths.build_root not in required.values()
