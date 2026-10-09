"""VM-visible all-artifact preflight, through real nested Bash and fake SSH."""
import json
import os
from pathlib import Path

import pytest

from test_fpga_agent import board  # noqa: F401


@pytest.mark.parametrize('name', ['gpgpu_platform.bit', 'ps7_init.tcl', 'gpgpu_host.elf'])
@pytest.mark.parametrize('directory', [False, True])
def test_missing_remote_artifact_prevents_every_board_helper(board, name, directory):
    repo, invoke, records = board
    uploaded = Path(os.environ['FPGA_UPLOADED'])
    artifact = uploaded / name
    artifact.unlink()
    if directory:
        artifact.mkdir()
    result = invoke('fpga:program')
    assert result.exit_code != 0, result.output
    assert records() == [], 'Preflight must not select/reset/mode/program the board'
    metadata = json.loads((repo / 'logs/latest/run.json').read_text())
    stage = next(t for t in metadata['tasks'] if t['task'] == 'fpga:preflight')
    assert stage['status'] == 'failed'
    assert metadata['exit_code'] == 1
    assert '/home/njason/upload/' + name in (repo / 'logs/latest' / stage['log']).read_text()
    assert uploaded.joinpath('checks').read_text().splitlines() == [
        '/home/njason/upload/gpgpu_platform.bit', '/home/njason/upload/ps7_init.tcl',
        '/home/njason/upload/gpgpu_host.elf',
    ]


def test_preflight_reports_all_missing_paths_in_one_failed_stage(board):
    repo, invoke, records = board
    uploaded = Path(os.environ['FPGA_UPLOADED'])
    names = ['gpgpu_platform.bit', 'ps7_init.tcl', 'gpgpu_host.elf']
    for name in names:
        (uploaded / name).unlink()
    result = invoke('fpga:program')
    assert result.exit_code != 0
    assert records() == []
    metadata = json.loads((repo / 'logs/latest/run.json').read_text())
    stage = next(t for t in metadata['tasks'] if t['status'] == 'failed')
    assert stage['task'] == 'fpga:preflight'
    log = (repo / 'logs/latest' / stage['log']).read_text()
    for name in names:
        assert '/home/njason/upload/' + name in log


def test_remote_preflight_transport_failure_is_fail_closed(board):
    repo, invoke, records = board
    with Path.home().joinpath('.bashrc').open('a') as rc:
        rc.write('exit 23\n')
    result = invoke('fpga:program')
    assert result.exit_code != 0
    assert records() == []
    metadata = json.loads((repo / 'logs/latest/run.json').read_text())
    assert metadata['exit_code'] == 23
    assert next(t for t in metadata['tasks'] if t['status'] == 'failed')['task'] == 'fpga:preflight'


@pytest.mark.parametrize('task', ['fpga:reset', 'fpga:mode:project', 'fpga:mode:demo'])
def test_standalone_board_operations_do_not_need_uploaded_files(board, task):
    _, invoke, records = board
    uploaded = Path(os.environ['FPGA_UPLOADED'])
    for path in uploaded.iterdir():
        path.unlink()
    result = invoke(task)
    assert result.exit_code == 0, result.output
    assert len(records()) == 2
    assert not (uploaded / 'checks').exists()


def test_preflight_alone_is_read_only_and_always_runs(board):
    repo, invoke, records = board
    for _ in range(2):
        result = invoke('fpga:preflight')
        assert result.exit_code == 0, result.output
    assert records() == []
    assert len((Path(os.environ['FPGA_UPLOADED']) / 'checks').read_text().splitlines()) == 6
    metadata = json.loads((repo / 'logs/latest/run.json').read_text())
    assert [t['task'] for t in metadata['tasks']] == ['fpga:preflight']

