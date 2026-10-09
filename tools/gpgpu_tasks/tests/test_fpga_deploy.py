"""Deploy orchestration through copying fake SCP and real nested Bash fake SSH."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

from config import resolve_config
from test_fpga_agent import board  # noqa: F401
from test_fpga_tasks import artifacts, materialize


@pytest.fixture
def deployment(board, tmp_path, monkeypatch):
    repo, board_invoke, records = board
    uploaded = Path(os.environ['FPGA_UPLOADED'])
    for path in uploaded.iterdir():
        path.unlink()
    events = tmp_path / 'events.jsonl'
    monkeypatch.setenv('FPGA_DEPLOY_EVENTS', str(events))
    # Record read-only checks and each hardware helper in the same chronology
    # as transfers; keep the board fixture's forbidden real transports intact.
    with Path.home().joinpath('.bashrc').open('a') as rc:
        rc.write('printf "ssh\\n" >> "$FPGA_UPLOADED/ssh-sessions"\n')
        rc.write('function deployment_event { printf \'{"event":"%s"}\\n\' "$1" >> "$FPGA_DEPLOY_EVENTS"; }\n')
        rc.write('definition=$(declare -f test); eval "${definition/test/original_test}"\n')
        rc.write('function test { deployment_event preflight; original_test "$@"; }\n')
        rc.write('definition=$(declare -f record_helper); eval "${definition/record_helper/original_record_helper}"\n')
        rc.write('function record_helper { deployment_event "$1"; original_record_helper "$@"; }\n')
    fake = tmp_path / 'copy-scp'
    fake.write_text(
        f'#!{sys.executable}\n'
        'import json, os, pathlib, shutil, sys\n'
        "assert len(sys.argv) == 4 and sys.argv[1] == '--'\n"
        "source, remote = sys.argv[2:]\n"
        "destination, path = remote.split(':', 1)\n"
        "assert destination in ('njason@192.168.1.13', 'operator@board-alias')\n"
        "assert str(pathlib.PurePosixPath(path).parent) in ('/home/njason/upload', '/vm/files')\n"
        "with open(os.environ['FPGA_DEPLOY_EVENTS'], 'a') as f: f.write(json.dumps({'event': 'scp', 'source': source, 'remote': remote}) + '\\n')\n"
        "if os.environ.get('FPGA_SCP_FAIL'): sys.exit(7)\n"
        "target = pathlib.Path(os.environ['FPGA_UPLOADED']) / pathlib.PurePosixPath(path).name\n"
        "shutil.copyfile(source, target)\n"
        "if target.name == os.environ.get('FPGA_DROP_UPLOAD'): target.unlink()\n"
        "print('copied ' + remote, flush=True)\n"
    )
    fake.chmod(0o755)

    def invoke(task='fpga:deploy', *overrides):
        return board_invoke(task, f'tools.scp.command={fake}', *overrides)

    def chronology():
        return [json.loads(line) for line in events.read_text().splitlines()] if events.exists() else []

    config = resolve_config(repo)
    materialize(config)
    return repo, invoke, records, chronology, config


HELPERS = ['fuse', 'fr', 'fuse', 'fm', 'fuse', 'fpl', 'fuse', 'fps']
STAGES = ['fpga:upload', 'fpga:preflight', 'fpga:program:reset',
          'fpga:mode:project', 'fpga:program']  # Logger records actionable stages, not aggregates.


def test_deploy_uploads_before_whole_program_chain_through_logged_runner(deployment):
    repo, invoke, records, chronology, config = deployment
    result = invoke()
    assert result.exit_code == 0, result.output
    assert [event['event'] for event in chronology()] == ['scp'] * 3 + ['preflight'] * 3 + HELPERS
    assert [record['helper'] for record in records()] == HELPERS
    uploaded = Path(os.environ['FPGA_UPLOADED'])
    for source, name in zip(artifacts(config), ['gpgpu_platform.bit', 'ps7_init.tcl', 'gpgpu_host.elf']):
        assert (uploaded / name).read_bytes() == source.read_bytes()
    metadata = json.loads((repo / 'logs/latest/run.json').read_text())
    assert [stage['task'] for stage in metadata['tasks']] == STAGES
    assert all(stage['status'] == 'success' for stage in metadata['tasks'])
    for stage in metadata['tasks']:
        assert (repo / 'logs/latest' / stage['log']).is_file()
    assert 'copied ' in (repo / 'logs/latest' / metadata['tasks'][0]['log']).read_text()
    assert 'helper fps ok' in (repo / 'logs/latest' / metadata['tasks'][-1]['log']).read_text()


@pytest.mark.parametrize('position', [0, 1, 2])
@pytest.mark.parametrize('directory', [False, True])
def test_deploy_missing_local_artifact_stops_before_any_transport(deployment, position, directory):
    repo, invoke, records, chronology, config = deployment
    missing = artifacts(config)[position]
    missing.unlink()
    if directory:
        missing.mkdir()
    result = invoke()
    assert result.exit_code == 2, result.output
    assert chronology() == []
    assert records() == []
    assert not (Path(os.environ['FPGA_UPLOADED']) / 'ssh-sessions').exists()
    metadata = json.loads((repo / 'logs/latest/run.json').read_text())
    stage = next(stage for stage in metadata['tasks'] if stage['status'] == 'failed')
    assert stage['task'] == 'fpga:upload'
    assert str(missing) in (repo / 'logs/latest' / stage['log']).read_text()


def test_deploy_failed_scp_stops_before_preflight(deployment, monkeypatch):
    repo, invoke, records, chronology, _ = deployment
    monkeypatch.setenv('FPGA_SCP_FAIL', '1')
    result = invoke()
    assert result.exit_code == 2, result.output
    assert [event['event'] for event in chronology()] == ['scp']
    assert records() == []
    assert not (Path(os.environ['FPGA_UPLOADED']) / 'ssh-sessions').exists()
    metadata = json.loads((repo / 'logs/latest/run.json').read_text())
    assert metadata['exit_code'] == 7
    assert next(stage for stage in metadata['tasks'] if stage['status'] == 'failed')['task'] == 'fpga:upload'


@pytest.mark.parametrize('missing', ['gpgpu_platform.bit', 'ps7_init.tcl', 'gpgpu_host.elf'])
def test_deploy_remote_preflight_failure_after_upload_stops_all_helpers(deployment, monkeypatch, missing):
    repo, invoke, records, chronology, _ = deployment
    monkeypatch.setenv('FPGA_DROP_UPLOAD', missing)
    result = invoke()
    assert result.exit_code == 2, result.output
    assert [event['event'] for event in chronology()] == ['scp'] * 3 + ['preflight'] * 3
    assert records() == []
    assert (Path(os.environ['FPGA_UPLOADED']) / 'ssh-sessions').read_text().splitlines() == ['ssh']
    metadata = json.loads((repo / 'logs/latest/run.json').read_text())
    assert metadata['exit_code'] == 1
    assert next(stage for stage in metadata['tasks'] if stage['status'] == 'failed')['task'] == 'fpga:preflight'


def test_deploy_repeats_upload_and_whole_program_with_unchanged_artifacts(deployment):
    repo, invoke, records, chronology, _ = deployment
    for _ in range(2):
        result = invoke()
        assert result.exit_code == 0, result.output
    assert [event['event'] for event in chronology()] == (['scp'] * 3 + ['preflight'] * 3 + HELPERS) * 2
    assert [record['helper'] for record in records()] == HELPERS * 2
    runs = list((repo / 'logs/runs').iterdir())
    assert len(runs) == 2
    for run in runs:
        metadata = json.loads((run / 'run.json').read_text())
        assert [stage['task'] for stage in metadata['tasks']] == STAGES


def test_program_only_never_uploads_with_missing_local_artifacts(deployment):
    repo, invoke, records, chronology, config = deployment
    uploaded = Path(os.environ['FPGA_UPLOADED'])
    for source, name in zip(artifacts(config), ['gpgpu_platform.bit', 'ps7_init.tcl', 'gpgpu_host.elf']):
        (uploaded / name).write_bytes(source.read_bytes())
        source.unlink()
    result = invoke('fpga:program')
    assert result.exit_code == 0, result.output
    assert [event['event'] for event in chronology()] == ['preflight'] * 3 + HELPERS
    assert [record['helper'] for record in records()] == HELPERS
    metadata = json.loads((repo / 'logs/latest/run.json').read_text())
    assert [stage['task'] for stage in metadata['tasks']] == STAGES[1:]
    assert all(not path.exists() for path in artifacts(config)), 'No automatic vendor builds'


def test_deploy_custom_names_distinct_vm_and_agent_directories(deployment):
    repo, invoke, records, chronology, _ = deployment
    overrides = (
        'hardware.vivado.top=custom_wrapper',
        'hardware.vitis.platform_name=custom_platform',
        'hardware.vitis.host_name=custom_host',
        'hardware.fpga.upload.destination=operator@board-alias',
        'hardware.fpga.upload.directory=/vm/files',
        'hardware.fpga.agent.directory=/container/files',
    )
    config = resolve_config(repo, overrides=list(overrides))
    materialize(config)
    result = invoke('fpga:deploy', *overrides)
    assert result.exit_code == 0, result.output
    assert [event['remote'] for event in chronology() if event['event'] == 'scp'] == [
        f'operator@board-alias:/vm/files/{name}'
        for name in ['custom_platform.bit', 'ps7_init.tcl', 'custom_host.elf']
    ]
    uploaded = Path(os.environ['FPGA_UPLOADED'])
    assert uploaded.joinpath('checks').read_text().splitlines() == [
        '/vm/files/custom_platform.bit', '/vm/files/ps7_init.tcl', '/vm/files/custom_host.elf',
    ]
    assert next(record for record in records() if record['helper'] == 'fpl')['args'] == ['/container/files/custom_platform.bit']
    assert records()[-1]['args'] == ['/container/files/ps7_init.tcl', '/container/files/custom_host.elf']


def test_deploy_graph_reuses_program_without_build_dependencies(deployment):
    from test_fpga_tasks import fpga_module

    _, _, _, _, config = deployment
    tasks = {task['name']: task for task in fpga_module().create_tasks(config)}
    deploy = tasks['fpga:deploy']
    assert deploy['task_dep'] == ['fpga:upload']
    assert deploy['setup'] == ['fpga:program']
    assert deploy['actions'] == []
    assert deploy['uptodate'] == [False]
    assert deploy.get('file_dep', []) == []
    assert deploy.get('targets', []) == []
    assert tasks['fpga:upload']['task_dep'] == []
    assert tasks['fpga:program']['task_dep'] == ['fpga:program:reset']
    assert tasks['fpga:program']['setup'] == ['fpga:mode:project']
    assert tasks['fpga:program:reset']['task_dep'] == ['fpga:preflight']
    assert tasks['fpga:preflight']['task_dep'] == []
