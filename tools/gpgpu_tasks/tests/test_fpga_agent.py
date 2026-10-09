from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from cli.cli import create_app
from config import resolve_config
from test_fpga_tasks import REPO_ROOT


@pytest.fixture
def board(tmp_path, monkeypatch):
    import src.doit as task_runner

    monkeypatch.setattr(task_runner, "_TASK_MODULES", ("tools/hardware/fpga/tasks.py",))
    repo = tmp_path / "repo"
    for relative in ("config/profiles/default.yaml", "tools/hardware/fpga/tasks.py"):
        target = repo / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO_ROOT / relative, target)
    trace = tmp_path / "helpers.jsonl"
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    forbidden = tmp_path / 'forbidden-bin'
    forbidden.mkdir()
    for name in ('curl', 'docker', 'scp', 'ssh'):
        executable = forbidden / name
        executable.write_text('#!/bin/sh\nprintf "Forbidden real transport\\n" >&2\nexit 99\n')
        executable.chmod(0o755)
    import os
    monkeypatch.setenv('PATH', str(forbidden) + os.pathsep + os.environ['PATH'])
    monkeypatch.setenv("FPGA_TRACE", str(trace))
    state = tmp_path / "mode"
    state.write_text("project")
    monkeypatch.setenv("FPGA_MODE_FILE", str(state))
    uploaded = tmp_path / "uploaded"
    uploaded.mkdir()
    for name in ('gpgpu_platform.bit', 'ps7_init.tcl', 'gpgpu_host.elf', 'custom_platform.bit', 'custom_host.elf'):
        (uploaded / name).write_text('synthetic artifact')
    monkeypatch.setenv('FPGA_UPLOADED', str(uploaded))
    recorder = tmp_path / "record-helper"
    recorder.write_text(
        f"#!{sys.executable}\n"
        "import json, os, pathlib, sys\n"
        "name, *args = sys.argv[1:]\n"
        "state = pathlib.Path(os.environ['FPGA_MODE_FILE'])\n"
        "record = {'helper': name, 'args': args, 'device': os.environ.get('FPGA_DEV'), 'mode': state.read_text(), 'ssh': json.loads(os.environ['FAKE_SSH_ARGV']), 'remote': os.environ['FAKE_SSH_REMOTE']}\n"
        "with open(os.environ['FPGA_TRACE'], 'a') as f: f.write(json.dumps(record) + '\\n')\n"
        "if name == os.environ.get('FPGA_FAIL'):\n"
        "    print('fake helper failure', flush=True); sys.exit(23)\n"
        "if name == 'fm': state.write_text(args[0])\n"
        "print('helper ' + name + ' ok', flush=True)\n"
    )
    recorder.chmod(0o755)
    # Mimic the real interactive-only .bashrc guard: bash -c would miss these.
    home.joinpath(".bashrc").write_text(
        'case $- in *i*) ;; *) return ;; esac\n'
        'function test {\n'
        '  if [[ "$1" == -f && ( "$2" == /home/njason/upload/* || "$2" == /vm/files/* ) ]]; then\n'
        '    printf "%s\\n" "$2" >> "$FPGA_UPLOADED/checks"\n'
        '    builtin test -f "$FPGA_UPLOADED/${2##*/}"\n'
        '  else return 99; fi\n'
        '}\n'
        f'function record_helper {{ {recorder} "$@"; }}\n'
        'function fuse { export FPGA_DEV="$1"; record_helper fuse "$@"; }\n'
        + ''.join(f'function {name} {{ record_helper {name} "$@"; }}\n'
                  for name in ("fr", "fm", "fpl", "fps"))
        )
    fake = tmp_path / "fake-ssh"
    fake.write_text(
        f"#!{sys.executable}\n"
        "import json, os, shlex, subprocess, sys\n"
        "if shlex.split(sys.argv[-1])[:2] != ['bash', '-ic']: sys.exit(99)\n"
        "os.environ['FAKE_SSH_ARGV'] = json.dumps(sys.argv[1:-1])\n"
        "os.environ['FAKE_SSH_REMOTE'] = sys.argv[-1]\n"
        "sys.exit(subprocess.run(['/bin/sh', '-c', sys.argv[-1]]).returncode)\n"
    )
    fake.chmod(0o755)
    (repo / "config/local.yaml").write_text(f"tools:\n  ssh:\n    command: {fake}\n")

    def invoke(task, *overrides):
        args = [part for override in overrides for part in ("--set", override)]
        return CliRunner().invoke(create_app(repo_root=repo), [*args, "run", task, "--plain"])

    def records():
        return [json.loads(line) for line in trace.read_text().splitlines()] if trace.exists() else []

    return repo, invoke, records


def test_reset_preserves_lowercase_current_mode_through_logged_cli(board):
    repo, invoke, records = board
    result = invoke("fpga:reset")
    assert result.exit_code == 0, result.output
    select, reset = records()
    assert select['helper'] == 'fuse'
    assert select['args'] == ['210299730789']
    assert reset['helper'] == 'fr'
    assert reset['args'] == []
    assert reset['mode'] == 'project'
    assert reset['device'] == '210299730789'
    assert 'helper fr ok' in ''.join(p.read_text() for p in (repo / 'logs/latest').glob('*.log'))


@pytest.mark.parametrize('mode', ['project', 'demo'])
def test_standalone_mode_only_changes_mode_and_repeats(board, mode):
    _, invoke, records = board
    for _ in range(2):
        result = invoke('fpga:mode:' + mode)
        assert result.exit_code == 0, result.output
    assert [r['helper'] for r in records()] == ['fuse', 'fm'] * 2
    assert all(r['args'] == [mode] for r in records() if r['helper'] == 'fm')


def test_program_orders_reset_mode_pl_ps_and_repeats_without_upload_or_build(board):
    repo, invoke, records = board
    for iteration in range(2):
        result = invoke('fpga:program')
        assert result.exit_code == 0, result.output
        batch = records()[iteration * 8:]
        assert [r['helper'] for r in batch] == ['fuse', 'fr', 'fuse', 'fm', 'fuse', 'fpl', 'fuse', 'fps']
        assert batch[3]['args'] == ['project']
        config = resolve_config(repo)
        directory = config.get('hardware.fpga.agent.directory')
        if directory is None:
            directory = config.get('hardware.fpga.upload.directory')
        assert batch[5]['args'] == [f'{directory}/gpgpu_platform.bit']
        assert batch[7]['args'] == [f'{directory}/ps7_init.tcl', f'{directory}/gpgpu_host.elf']
        assert all(r['device'] == '210299730789' for r in batch)
    metadata = json.loads((repo / 'logs/latest/run.json').read_text())
    assert [task['task'] for task in metadata['tasks']] == ['fpga:preflight', 'fpga:program:reset', 'fpga:mode:project', 'fpga:program']
    assert not (repo / 'build/hardware').exists()
    import os
    checks = Path(os.environ['FPGA_UPLOADED']) / 'checks'
    assert len(checks.read_text().splitlines()) == 6, 'Preflight must run on every invocation'


@pytest.mark.parametrize('helper,count', [('fuse', 1), ('fr', 2), ('fm', 4), ('fpl', 6), ('fps', 8)])
def test_program_short_circuits_failures_and_records_transport_status(board, monkeypatch, helper, count):
    repo, invoke, records = board
    monkeypatch.setenv('FPGA_FAIL', helper)
    result = invoke('fpga:program')
    assert result.exit_code == 2, result.output
    assert len(records()) == count
    metadata = json.loads((repo / 'logs/latest/run.json').read_text())
    assert metadata['exit_code'] == 23
    assert next(task for task in metadata['tasks'] if task.get('exit_code') == 23)['status'] == 'failed'
    if helper != 'fuse':
        assert 'fake helper failure' in ''.join(p.read_text() for p in (repo / 'logs/latest').glob('*.log'))


@pytest.mark.parametrize('helper,expected', [
    ('fr', ['fuse']), ('fm', ['fuse', 'fr', 'fuse']),
    ('fpl', ['fuse', 'fr', 'fuse', 'fm', 'fuse']),
    ('fps', ['fuse', 'fr', 'fuse', 'fm', 'fuse', 'fpl', 'fuse']),
])
def test_missing_shell_helper_is_logged_and_stops_program(board, helper, expected):
    repo, invoke, records = board
    home = Path.home()
    with home.joinpath('.bashrc').open('a') as rc:
        rc.write(f'unset -f {helper}\n')
    result = invoke('fpga:program')
    assert result.exit_code == 2, result.output
    assert [r['helper'] for r in records()] == expected
    assert json.loads((repo / 'logs/latest/run.json').read_text())['exit_code'] == 127
    assert f'{helper}: command not found' in ''.join(p.read_text() for p in (repo / 'logs/latest').glob('*.log'))


@pytest.mark.parametrize('key,value', [
    *[('tools.ssh.command', value) for value in ('null', '42', '[]', "''", 'ssh -v', '-ssh')],
    *[('hardware.fpga.upload.destination', value) for value in ('null', '42', "''", '-board', 'user@-board', 'board;touch', 'user@@board')],
    *[('hardware.fpga.agent.device', value) for value in ('null', '42', '[]', "''", '..', '../device', '-device', 'board?mode=DEMO')],
])
def test_bad_transport_config_fails_at_action_without_ssh_and_keeps_discovery(board, key, value):
    import src.doit as task_runner

    repo, invoke, records = board
    override = f'{key}={value}'
    baseline = {task.name for task in task_runner.create_task_loader(resolve_config(repo)).load_tasks(None, [])}
    config = resolve_config(repo, overrides=[override])
    assert {task.name for task in task_runner.create_task_loader(config).load_tasks(None, [])} == baseline
    for task in ('fpga:reset', 'fpga:program'):
        result = invoke(task, override)
        assert result.exit_code == 2, result.output
        assert key in result.output
        assert records() == []


def test_program_uses_shared_upload_names_and_agent_mount_override(board):
    _, invoke, records = board
    result = invoke('fpga:program',
        'hardware.fpga.upload.destination=operator@board-alias',
        'hardware.fpga.upload.directory=/vm/files',
        'hardware.fpga.agent.directory=/container/files',
        'hardware.fpga.agent.device=board-1',
        'hardware.vitis.platform_name=custom_platform',
        'hardware.vitis.host_name=custom_host',
    )
    assert result.exit_code == 0, result.output
    assert all(r['ssh'][-1] == 'operator@board-alias' for r in records())
    assert all(r['device'] == 'board-1' for r in records())
    assert next(r for r in records() if r['helper'] == 'fpl')['args'] == ['/container/files/custom_platform.bit']
    assert records()[-1]['args'] == ['/container/files/ps7_init.tcl', '/container/files/custom_host.elf']
    import os
    assert (Path(os.environ['FPGA_UPLOADED']) / 'checks').read_text().splitlines() == [
        '/vm/files/custom_platform.bit', '/vm/files/ps7_init.tcl', '/vm/files/custom_host.elf',
    ]


@pytest.mark.parametrize('key,value', [
    *[(key, value) for key in ('hardware.fpga.agent.directory', 'hardware.fpga.upload.directory')
      for value in ('42', '[]', "''", 'relative', '/files/../other', '/files;touch')],
    *[(key, value) for key in ('hardware.vitis.platform_name', 'hardware.vitis.host_name')
      for value in ('null', '42', '[]', "''", '..', '../escape', '-name', 'bad;touch')],
    ('hardware.fpga.upload.directory', 'null'),
])
def test_program_validates_entire_filename_batch_before_programming(board, key, value):
    _, invoke, records = board
    result = invoke('fpga:program', f'{key}={value}')
    assert result.exit_code == 2, result.output
    assert key in result.output
    assert records() == [], 'Invalid programming inputs must fail before board mutation'


@pytest.mark.parametrize('pretty', [False, True])
@pytest.mark.parametrize('helper,missing', [
    ('fpl', '/home/njason/upload/gpgpu_platform.bit'),
    ('fps', '/home/njason/upload/ps7_init.tcl'),
    ('fps', '/home/njason/upload/gpgpu_host.elf'),
])
def test_missing_agent_file_response_fails_even_when_helper_returns_zero(board, helper, missing, pretty):
    repo, invoke, records = board
    detail = f'Programming file does not exist or is not a file: {missing}'
    # Real Agent HTTP-error bodies can be returned with a successful shell status.
    response = json.dumps({'detail': detail}, indent=2 if pretty else None)
    with Path.home().joinpath('.bashrc').open('a') as rc:
        rc.write(f"function {helper} {{ printf '%s\\n' 'helper response:' '{response}'; }}\n")

    result = invoke('fpga:program')

    assert result.exit_code != 0, result.output
    metadata = json.loads((repo / 'logs/latest/run.json').read_text())
    stage = next(task for task in metadata['tasks'] if task['task'] == 'fpga:program')
    assert stage['status'] == 'failed'
    assert metadata['exit_code'] != 0
    assert missing in (repo / 'logs/latest' / stage['log']).read_text()
    if helper == 'fpl':
        assert all(record['helper'] != 'fps' for record in records())


def test_run_help_documents_remote_board_commands(board):
    repo, _, _ = board
    result = CliRunner().invoke(create_app(repo_root=repo), ['run', '--help'], env={'COLUMNS': '180'})
    assert result.exit_code == 0, result.output
    for task in ('fpga:preflight', 'fpga:program:reset', 'fpga:reset', 'fpga:program', 'fpga:mode:project', 'fpga:mode:demo'):
        assert task in result.output
