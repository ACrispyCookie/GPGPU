"""SSH shell-shortcut transport and explicit programming-stage contract."""

import json
import shlex

from config import resolve_config
from src import create_task_loader
from test_fpga_agent import board  # noqa: F401: reusable isolated fake-SSH fixture


def test_ssh_executes_nested_interactive_bash_without_direct_api_transport(board):
    _, invoke, records = board
    result = invoke("fpga:mode:demo")
    assert result.exit_code == 0, result.output
    select, mode = records()
    assert select['ssh'] == ['-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10', '--', 'njason@192.168.1.13']
    remote = shlex.split(mode['remote'])
    assert remote[:2] == ['bash', '-ic']
    assert len(remote) == 3
    assert remote[2] == 'set -e; set -o pipefail; fuse 210299730789 >/dev/null; fm demo'
    assert mode['remote'] == shlex.join(remote)
    for obsolete in ('curl', 'docker', 'socket', 'http://'):
        assert obsolete not in mode['remote']


def test_defaults_do_not_configure_an_inaccessible_vm_socket(board):
    repo, _, _ = board
    assert 'socket' not in resolve_config(repo).get('hardware.fpga.agent')


def test_program_graph_orders_preflight_reset_then_project_setup_before_program(board):
    repo, invoke, _ = board
    tasks = {task.name: task for task in create_task_loader(resolve_config(repo)).load_tasks(None, [])}
    assert tasks['fpga:program'].task_dep == ['fpga:program:reset']
    assert tasks['fpga:program:reset'].task_dep == ['fpga:preflight']
    assert tasks['fpga:preflight'].task_dep == []
    assert tasks['fpga:reset'].task_dep == []
    assert tasks['fpga:reset'].actions[0].py_callable is tasks['fpga:program:reset'].actions[0].py_callable
    assert tasks['fpga:program'].setup_tasks == ['fpga:mode:project']
    assert tasks['fpga:mode:project'].task_dep == []
    assert tasks['fpga:mode:demo'].task_dep == []
    result = invoke('fpga:program')
    assert result.exit_code == 0, result.output
    metadata = json.loads((repo / 'logs/latest/run.json').read_text())
    assert [task['task'] for task in metadata['tasks']] == [
        'fpga:preflight', 'fpga:program:reset', 'fpga:mode:project', 'fpga:program',
    ]
