from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

import pytest

from config import resolve_config

REPO_ROOT = Path(__file__).resolve().parents[3]
MODULE_PATH = REPO_ROOT / "tools/hardware/fpga/tasks.py"


def fpga_module():
    assert MODULE_PATH.is_file(), "Separate FPGA task module must exist"
    spec = importlib.util.spec_from_file_location("fpga_tasks_under_test", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def upload_config(tmp_path, *overrides):
    return resolve_config(REPO_ROOT, overrides=[f"paths.build.root={tmp_path / 'build'}", *overrides])


def artifacts(config):
    root = config.build_root
    platform = config.get("hardware.vitis.platform_name")
    host = config.get("hardware.vitis.host_name")
    return (
        root / "hardware/bitstream" / f"{config.get('hardware.vivado.top')}.bit",
        root / "software/vitis" / platform / "export" / platform / "hw/sdt/ps7_init.tcl",
        root / "software/vitis" / host / "build" / f"{host}.elf",
    )


def materialize(config):
    for path in artifacts(config):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("test artifact\n")


def execute(task):
    action, args = task["actions"][0]
    return action(*args)


def test_upload_transfers_existing_artifacts_with_default_remote_filenames(tmp_path, monkeypatch):
    config = upload_config(tmp_path)
    materialize(config)
    calls = []
    monkeypatch.setattr(subprocess, "run", lambda argv, **kwargs: calls.append((argv, kwargs)))
    task = next(task for task in fpga_module().create_tasks(config) if task["name"] == "fpga:upload")

    execute(task)

    assert [argv for argv, _ in calls] == [
        ["scp", "--", str(path), f"njason@192.168.1.13:/home/njason/upload/{name}"]
        for path, name in zip(artifacts(config), ("gpgpu_platform.bit", "ps7_init.tcl", "gpgpu_host.elf"))
    ]
    assert all(kwargs == {"cwd": config.repo_root, "check": True} for _, kwargs in calls)


@pytest.mark.parametrize("missing_index", [0, 1, 2])
def test_missing_artifact_is_reported_before_any_network_transfer(tmp_path, monkeypatch, missing_index):
    config = upload_config(tmp_path)
    materialize(config)
    missing = artifacts(config)[missing_index]
    missing.unlink()
    calls = []
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: calls.append(args))
    task = next(task for task in fpga_module().create_tasks(config) if task["name"] == "fpga:upload")

    with pytest.raises(FileNotFoundError, match=str(missing)):
        execute(task)

    assert calls == []


def test_program_preflight_graph_has_no_build_upload_or_file_dependencies(tmp_path):
    tasks = {task['name']: task for task in fpga_module().create_tasks(upload_config(tmp_path))}
    assert tasks['fpga:program']['task_dep'] == ['fpga:program:reset']
    assert tasks['fpga:program']['setup'] == ['fpga:mode:project']
    assert tasks['fpga:program:reset']['task_dep'] == ['fpga:preflight']
    assert tasks['fpga:preflight']['task_dep'] == []
    assert tasks['fpga:reset']['task_dep'] == []
    assert tasks['fpga:program:reset']['actions'] == tasks['fpga:reset']['actions']
    for name in ('fpga:preflight', 'fpga:program:reset', 'fpga:program'):
        assert tasks[name]['uptodate'] == [False]
        assert tasks[name].get('file_dep', []) == []
        assert tasks[name].get('targets', []) == []


def test_upload_is_always_requested_without_build_dependencies(tmp_path):
    task = next(task for task in fpga_module().create_tasks(upload_config(tmp_path)) if task["name"] == "fpga:upload")

    assert task["name"] == "fpga:upload"
    assert task["task_dep"] == []
    assert task["uptodate"] == [False]
    assert task.get("file_dep", []) == []
    assert task.get("targets", []) == []


def test_loader_discovers_fpga_upload(tmp_path):
    from src import create_task_loader

    tasks = create_task_loader(upload_config(tmp_path)).load_tasks(None, [])

    assert "fpga:upload" in [task.name for task in tasks]


def test_configured_names_build_root_and_destination_are_passed_as_literal_argv(tmp_path, monkeypatch):
    config = upload_config(
        tmp_path,
        f"paths.build.root={tmp_path / 'output with spaces'}",
        "hardware.vivado.top=custom_wrapper",
        "hardware.vitis.platform_name=custom_platform",
        "hardware.vitis.host_name=custom_host",
        "hardware.fpga.upload.destination=operator@example.test",
        "hardware.fpga.upload.directory=/srv/board_uploads",
        "tools.scp.command=/opt/fake-scp",
    )
    materialize(config)
    calls = []
    monkeypatch.setattr(subprocess, "run", lambda argv, **kwargs: calls.append((argv, kwargs)))

    execute(fpga_module().create_tasks(config)[0])

    assert [argv for argv, _ in calls] == [
        ["/opt/fake-scp", "--", str(path), f"operator@example.test:/srv/board_uploads/{name}"]
        for path, name in zip(artifacts(config), ("custom_platform.bit", "ps7_init.tcl", "custom_host.elf"))
    ]
    assert all("shell" not in kwargs for _, kwargs in calls)


@pytest.mark.parametrize("command", [None, 42, [], "", " ", "scp -O", "scp\n-O", "scp;touch", "-scp"])
def test_invalid_upload_command_is_rejected_before_subprocess(tmp_path, monkeypatch, command):
    source = tmp_path / "existing.bit"
    source.write_text("artifact")
    calls = []
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: calls.append(args))

    with pytest.raises(ValueError, match=r"tools\.scp\.command"):
        fpga_module().upload_artifacts(((source, "safe.bit"),), command, "board", "/upload", tmp_path)

    assert calls == []


@pytest.mark.parametrize("key,value", [
    *[("destination", value) for value in (
        None, 42, [], "", "-board", "user@-board", "-user@board", "@board", "user@",
        "user@@board", "board:22", "[::1]", "board name", "board;touch", "$(touch)",
        "board\n", "böard", "user/name@board",
    )],
    *[("directory", value) for value in (
        None, 42, [], "", "relative", "~/upload", "/upload space", "/upload;touch",
        "/$(touch)", "/upload:other", "/upload/../other", "/../upload", "/upload\n",
        "/ümlaut", "/upload/*", "/upload/`touch`", "/upload\\other",
    )],
])
def test_invalid_remote_config_is_rejected_before_subprocess(tmp_path, monkeypatch, key, value):
    source = tmp_path / "existing.bit"
    source.write_text("artifact")
    calls = []
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: calls.append(args))
    options = {"command": "scp", "destination": "board", "directory": "/upload", "cwd": tmp_path}
    options[key] = value

    with pytest.raises(ValueError, match=rf"hardware\.fpga\.upload\.{key}"):
        fpga_module().upload_artifacts(((source, "safe.bit"),), **options)

    assert calls == []


@pytest.mark.parametrize("filename", [
    None, 42, [], "", ".", "..", "../escape.bit", "/escape.bit", "sub/file.bit",
    "bad file.bit", "bad;touch.bit", "$(touch).bit", "bad:other.bit", "-bad.bit", "bäd.bit",
])
def test_all_remote_filenames_are_validated_before_first_transfer(tmp_path, monkeypatch, filename):
    source = tmp_path / "existing.bit"
    source.write_text("artifact")
    calls = []
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: calls.append(args))

    with pytest.raises(ValueError, match=r"hardware\.fpga\.upload\.filenames"):
        fpga_module().upload_artifacts(
            ((source, "safe.bit"), (source, filename)), "scp", "board", "/upload", tmp_path,
        )

    assert calls == []


@pytest.mark.parametrize("key", ["hardware.vitis.platform_name", "hardware.vitis.host_name"])
@pytest.mark.parametrize("value", [None, 42, [], "", "..", "../escape", "bad;touch", "bad name", "-bad"])
def test_configured_artifact_names_are_validated_only_at_action_time(tmp_path, monkeypatch, key, value):
    config = upload_config(tmp_path)
    original_get = config.get
    monkeypatch.setattr(type(config), "get", lambda self, name, *args: value if name == key else original_get(name, *args))
    calls = []
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: calls.append(args))

    task = next(task for task in fpga_module().create_tasks(config) if task["name"] == "fpga:upload")
    with pytest.raises(ValueError, match=key):
        execute(task)

    assert calls == []


@pytest.mark.parametrize("override", [
    "tools.scp.command=null", "hardware.fpga.upload.destination=null",
    "hardware.fpga.upload.directory=null", "hardware.fpga.upload.directory=relative",
])
def test_invalid_upload_config_does_not_prevent_unrelated_task_loading(tmp_path, override):
    from src import create_task_loader

    config = upload_config(tmp_path, override)
    baseline = {task.name for task in create_task_loader(upload_config(tmp_path)).load_tasks(None, [])}
    loaded = {task.name for task in create_task_loader(config).load_tasks(None, [])}

    assert loaded == baseline
    assert loaded - {"fpga:upload"}


@pytest.mark.parametrize("destination,directory", [
    ("board-alias_1", "/"),
    ("user.name_1@board.example-test", "/srv/board_uploads/"),
    ("192.168.1.13", "/srv/board-1.2"),
])
def test_safe_remote_alias_and_posix_directory_are_accepted(tmp_path, monkeypatch, destination, directory):
    source = tmp_path / "local artifact with spaces.bit"
    source.write_text("artifact")
    calls = []
    monkeypatch.setattr(subprocess, "run", lambda argv, **kwargs: calls.append(argv))

    fpga_module().upload_artifacts(((source, "safe-1.2.bit"),), "scp", destination, directory, tmp_path)

    assert calls == [["scp", "--", str(source), f"{destination}:{directory.rstrip('/')}/safe-1.2.bit"]]


def test_transport_failure_stops_remaining_transfers(tmp_path, monkeypatch):
    config = upload_config(tmp_path)
    materialize(config)
    calls = []

    def failing_transport(argv, **kwargs):
        calls.append(argv)
        raise subprocess.CalledProcessError(7, argv)

    monkeypatch.setattr(subprocess, "run", failing_transport)
    with pytest.raises(subprocess.CalledProcessError) as failure:
        execute(fpga_module().create_tasks(config)[0])

    assert failure.value.returncode == 7
    assert len(calls) == 1


def logged_config(tmp_path):
    import shutil
    import sys

    repo = tmp_path / "repo"
    for relative in ("config/profiles/default.yaml", "tools/hardware/fpga/tasks.py"):
        target = repo / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO_ROOT / relative, target)
    fake = tmp_path / "fake-scp"
    fake.write_text(
        f"#!{sys.executable}\n"
        "import os, sys\n"
        "print('fake transport: ' + repr(sys.argv[1:]), flush=True)\n"
        "sys.exit(int(os.environ.get('FPGA_TEST_EXIT', '0')))\n"
    )
    fake.chmod(0o755)
    return resolve_config(repo, overrides=[f"tools.scp.command={fake}"])


def test_logged_upload_runs_again_even_with_unchanged_artifacts(tmp_path, monkeypatch):
    import src.doit as task_runner

    monkeypatch.setattr(task_runner, "_TASK_MODULES", ("tools/hardware/fpga/tasks.py",))
    config = logged_config(tmp_path)
    materialize(config)

    assert task_runner.run_logged_task(config, "fpga:upload") == 0
    assert task_runner.run_logged_task(config, "fpga:upload") == 0

    runs = list((config.repo_root / "logs/runs").iterdir())
    assert len(runs) == 2
    for run in runs:
        log, = run.glob("*.log")
        assert log.read_text().count("fake transport:") == 3


def test_logged_upload_propagates_failure_with_transport_exit_code(tmp_path, monkeypatch):
    import json

    import src.doit as task_runner

    monkeypatch.setattr(task_runner, "_TASK_MODULES", ("tools/hardware/fpga/tasks.py",))
    monkeypatch.setenv("FPGA_TEST_EXIT", "7")
    config = logged_config(tmp_path)
    materialize(config)

    assert task_runner.run_logged_task(config, "fpga:upload") == 2

    latest = config.repo_root / "logs/latest"
    metadata = json.loads((latest / "run.json").read_text())
    assert metadata["exit_code"] == 7
    assert metadata["tasks"][0]["exit_code"] == 7
    log, = latest.glob("*.log")
    assert log.read_text().count("fake transport:") == 1


@pytest.mark.parametrize("transport_exit, cli_exit", [(0, 0), (7, 2)])
def test_cli_upload_uses_logged_task_runner_with_fake_transport(tmp_path, monkeypatch, transport_exit, cli_exit):
    import src.doit as task_runner
    from cli.cli import create_app
    from typer.testing import CliRunner

    monkeypatch.setattr(task_runner, "_TASK_MODULES", ("tools/hardware/fpga/tasks.py",))
    monkeypatch.setenv("FPGA_TEST_EXIT", str(transport_exit))
    config = logged_config(tmp_path)
    materialize(config)

    result = CliRunner().invoke(create_app(repo_root=config.repo_root), [
        "--set", f"tools.scp.command={config.get('tools.scp.command')}", "run", "fpga:upload",
    ])

    assert result.exit_code == cli_exit, result.output
    assert "Uploading" in result.output
    latest = config.repo_root / "logs/latest"
    assert (latest / "run.json").is_file()
    log, = latest.glob("*.log")
    assert "fake transport:" in log.read_text()
