"""Regression for Bash errexit inside a programming helper function."""
from pathlib import Path
import subprocess

import pytest

from config import resolve_config
from src import create_task_loader


def test_program_aborts_when_pl_helper_internal_command_fails(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    home.mkdir()
    marker = tmp_path / "ps-called"
    (home / ".bashrc").write_text(
        "case $- in *i*) ;; *) return ;; esac\n"
        "fuse() { export FPGA_DEV=\"$1\"; }\n"
        "fpl() { false; :; }\n"
        "fps() { touch \"$PS_MARKER\"; }\n",
        encoding="utf-8",
    )
    ssh = tmp_path / "ssh"
    ssh.write_text(
        "#!/usr/bin/env python3\nimport os,sys\n"
        'os.execv("/bin/sh", ["sh", "-c", sys.argv[-1]])\n',
        encoding="utf-8",
    )
    ssh.chmod(0o755)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("PS_MARKER", str(marker))
    repo = Path(__file__).resolve().parents[3]
    config = resolve_config(repo, overrides=[f"tools.ssh.command={ssh}"])
    tasks = {task.name: task for task in create_task_loader(config).load_tasks(None, [])}
    program_board = tasks["fpga:program"].actions[0].py_callable

    with pytest.raises(subprocess.CalledProcessError):
        program_board(config)

    assert not marker.exists(), "PS must not run after an internal PL helper failure"
