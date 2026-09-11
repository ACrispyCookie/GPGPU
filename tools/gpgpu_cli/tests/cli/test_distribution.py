from __future__ import annotations

import os
from pathlib import Path
import subprocess

import yaml


REPO_ROOT = Path(__file__).resolve().parents[4]
CLI_PROJECT = REPO_ROOT / "tools/gpgpu_cli"


def test_repository_has_default_profile_and_local_override_template() -> None:
    profile_path = REPO_ROOT / "config/profiles/default.yaml"
    template_path = REPO_ROOT / "config/local.yaml.example"

    profile = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
    assert profile["project"]["name"] == "ece338-gpgpu"
    assert profile["paths"]["hardware"]["rtl"] == "hardware/rtl"
    assert profile["tools"]["vivado"]["required"] is False
    assert template_path.is_file()


def test_root_launcher_is_executable_and_runs_cli() -> None:
    launcher = REPO_ROOT / "gpgpu"

    assert os.access(launcher, os.X_OK)
    launcher_text = launcher.read_text(encoding="utf-8")
    assert 'CLI_PROJECT="$ROOT/tools/gpgpu_cli"' in launcher_text
    assert 'uv sync --project "$CLI_PROJECT"' in launcher_text
    assert 'pip install --editable "$CLI_PROJECT"' in launcher_text
    assert "uv sync" in launcher_text
    assert "--extra" not in launcher_text
    assert "[dev]" not in launcher_text
    assert '"${1:-}" == "init"' not in launcher_text
    assert ".gpgpu-doctor-complete" in launcher_text
    assert '"$VENV/bin/gpgpu" doctor' in launcher_text
    assert "exit 0" not in launcher_text
    result = subprocess.run(
        [str(launcher), "config", "get", "project.name"],
        cwd=REPO_ROOT / "hardware/rtl",
        check=True,
        capture_output=True,
        text=True,
    )
    assert "ece338-gpgpu" in result.stdout
