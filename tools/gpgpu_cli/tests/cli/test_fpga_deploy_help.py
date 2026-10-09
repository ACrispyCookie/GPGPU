"""The FPGA command catalog distinguishes upload+program from program only."""
import pytest
from typer.testing import CliRunner

from cli.cli import create_app
from cli.commands.run import _TASK_HELP
from test_cli import make_repo


@pytest.mark.parametrize('width', [80, 140])
def test_run_help_lists_deploy_and_program_separately(tmp_path, monkeypatch, width):
    monkeypatch.setenv('COLUMNS', str(width))
    result = CliRunner().invoke(create_app(repo_root=make_repo(tmp_path)), ['run', '--help'])
    assert result.exit_code == 0, result.output
    assert 'fpga:deploy' in result.stdout
    assert 'fpga:program' in result.stdout
    deploy = next(row for row in _TASK_HELP.split('\n\n') if row.startswith('• `fpga:deploy`'))
    assert 'upload' in deploy.lower() and 'program' in deploy.lower()
    assert 'no build' in deploy.lower()
    program = next(row for row in _TASK_HELP.split('\n\n') if row.startswith('• `fpga:program`'))
    assert 'No build or upload is triggered' in program
