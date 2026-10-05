from __future__ import annotations

from pathlib import Path
import json
import os
import zipfile

import pytest

from tools.hardware.vitis import tasks as vitis


class StubResolvedConfig:
    def __init__(self, repo_root: Path) -> None:
        self.repo_root = repo_root
        self.vitis_command = "vitis-configured"
        self.cpu = "ps7_cortexa9_0"

    def get(self, key: str):
        values = {
            "hardware.vitis.version": "2026.1",
            "hardware.vitis.platform_name": "gpgpu_platform",
            "hardware.vitis.host_name": "gpgpu_host",
            "hardware.vitis.cpu": self.cpu,
            "hardware.vitis.domain": "standalone_ps7_cortexa9_0",
            "hardware.vitis.os": "standalone",
            "hardware.vitis.template": "empty_application",
            "hardware.vitis.default_archive": "tools/hardware/vitis/default-project.zip",
            "hardware.vitis.host_sources": [
                "software/host/xc7z020/gpgpu_host.c",
                "software/host/xc7z020/main.c",
            ],
            "tools.vitis.command": self.vitis_command,
        }
        return values[key]

    @property
    def build_root(self) -> Path:
        return self.repo_root / "build"


def make_repo(tmp_path: Path) -> StubResolvedConfig:
    for relative in (
        "build/hardware/platform/gpgpu_platform.xsa",
        "software/host/xc7z020/gpgpu_host.c",
        "software/host/xc7z020/main.c",
        "tools/hardware/vitis/vitis_flow.py",
    ):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("source\n", encoding="utf-8")

    archive = tmp_path / "tools/hardware/vitis/default-project.zip"
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr(
            "gpgpu_platform/vitis-comp.json",
            json.dumps(
                {
                    "name": "gpgpu_platform",
                    "type": "PLATFORM",
                    "configuration": {
                        "xsa": "${GPGPU_XSA}",
                        "xsaPathInPlatform": "gpgpu_platform/hw/gpgpu_platform.xsa",
                        "domains": [
                            {
                                "name": "standalone_ps7_cortexa9_0",
                                "processor": "ps7_cortexa9_0",
                                "os": "standalone",
                                "appTemplate": "empty_application",
                            }
                        ],
                    },
                }
            ),
        )
        output.writestr(
            "gpgpu_host/vitis-comp.json",
            json.dumps(
                {
                    "name": "gpgpu_host",
                    "type": "HOST",
                    "platform": "gpgpu_platform",
                    "domain": "standalone_ps7_cortexa9_0",
                    "cpuInstance": "ps7_cortexa9_0",
                    "os": "standalone",
                }
            ),
        )
        output.writestr(
            "gpgpu_host/src/UserConfig.cmake",
            'set(USER_COMPILE_SOURCES\n"${GPGPU_REPO_ROOT}/software/host/xc7z020/main.c"\n)\n',
        )
        output.writestr(
            "gpgpu_host/src/app.yaml",
            "template: empty_application\n",
        )
    return StubResolvedConfig(tmp_path)


def tasks_by_name(config: StubResolvedConfig) -> dict[str, dict]:
    return {task["name"]: task for task in vitis.create_tasks(config)}  # type: ignore[arg-type]


def test_vitis_tasks_form_requested_dependency_pipeline(tmp_path: Path) -> None:
    tasks = tasks_by_name(make_repo(tmp_path))

    assert list(tasks) == [
        "vitis:project",
        "vitis:build:platform",
        "vitis:build:host",
        "vitis:build:all",
        "vitis:export",
    ]
    assert tasks["vitis:project"]["task_dep"] == []
    assert tasks["vitis:build:platform"]["task_dep"] == ["vitis:project"]
    assert tasks["vitis:build:host"]["task_dep"] == ["vitis:build:platform"]
    assert tasks["vitis:build:all"]["task_dep"] == ["vitis:build:host"]
    assert tasks["vitis:export"].get("task_dep", []) == []
    assert tasks["vitis:export"]["uptodate"] == [False]


def test_vitis_project_builds_xsa_only_when_it_is_missing(tmp_path: Path) -> None:
    config = make_repo(tmp_path)
    (tmp_path / "build/hardware/platform/gpgpu_platform.xsa").unlink()

    tasks = tasks_by_name(config)

    assert tasks["vitis:project"]["task_dep"] == ["vivado:xsa"]


def test_vitis_tasks_keep_requested_workspace_and_artifact_targets(tmp_path: Path) -> None:
    tasks = tasks_by_name(make_repo(tmp_path))
    workspace = tmp_path / "build/software/vitis"

    assert tasks["vitis:project"]["targets"] == [
        str(workspace / "gpgpu_platform/vitis-comp.json"),
        str(workspace / "gpgpu_host/vitis-comp.json"),
    ]
    assert tasks["vitis:build:platform"]["targets"] == [
        str(workspace / "gpgpu_platform/export/gpgpu_platform/hw/gpgpu_platform.xsa"),
        str(workspace / "gpgpu_platform/export/gpgpu_platform/hw/sdt/ps7_init.tcl"),
        str(workspace / "gpgpu_platform/export/gpgpu_platform/gpgpu_platform.xpfm"),
    ]
    assert tasks["vitis:build:host"]["targets"] == [
        str(workspace / "gpgpu_host/build/gpgpu_host.elf")
    ]


def test_vitis_build_commands_use_configured_launcher_and_python_script(tmp_path: Path) -> None:
    tasks = tasks_by_name(make_repo(tmp_path))
    script = tmp_path / "tools/hardware/vitis/vitis_flow.py"
    workspace = tmp_path / "build/software/vitis"

    platform_command = tasks["vitis:build:platform"]["actions"][0][1][0]
    host_command = tasks["vitis:build:host"]["actions"][0][1][0]

    assert platform_command == [
        "vitis-configured",
        "-s",
        str(script),
        "--",
        "build",
        "--workspace",
        str(workspace),
        "--component",
        "gpgpu_platform",
    ]
    assert host_command == [
        "vitis-configured",
        "-s",
        str(script),
        "--",
        "build",
        "--workspace",
        str(workspace),
        "--component",
        "gpgpu_host",
    ]


def test_materialize_default_project_rewrites_only_generated_workspace_paths(
    tmp_path: Path,
) -> None:
    config = make_repo(tmp_path)
    archive = tmp_path / "tools/hardware/vitis/default-project.zip"
    workspace = tmp_path / "build/software/vitis"
    xsa = tmp_path / "build/hardware/platform/gpgpu_platform.xsa"

    vitis.materialize_default_project(
        archive,
        workspace,
        tmp_path,
        xsa,
        "gpgpu_platform",
        "gpgpu_host",
        "ps7_cortexa9_0",
        "standalone_ps7_cortexa9_0",
        "standalone",
        "empty_application",
        (
            tmp_path / "software/host/xc7z020/gpgpu_host.c",
            tmp_path / "software/host/xc7z020/main.c",
        ),
    )

    platform_metadata = json.loads(
        (workspace / "gpgpu_platform/vitis-comp.json").read_text(encoding="utf-8")
    )
    user_config = (workspace / "gpgpu_host/src/UserConfig.cmake").read_text(
        encoding="utf-8"
    )
    assert platform_metadata["configuration"]["xsa"] == str(xsa.resolve())
    assert str(tmp_path.resolve()) in user_config
    assert (workspace / "gpgpu_platform/hw/gpgpu_platform.xsa").read_text() == "source\n"
    assert user_config.count(str(tmp_path / "software/host/xc7z020")) == 2


def test_project_refresh_preserves_existing_workspace_edits(tmp_path: Path) -> None:
    config = make_repo(tmp_path)
    project_task = tasks_by_name(config)["vitis:project"]
    action, arguments = project_task["actions"][0]
    action(*arguments)

    workspace = tmp_path / "build/software/vitis"
    custom_edit = workspace / "gpgpu_host/src/custom.c"
    custom_edit.write_text("/* GUI edit */\n", encoding="utf-8")
    xsa = tmp_path / "build/hardware/platform/gpgpu_platform.xsa"
    xsa.write_text("new source\n", encoding="utf-8")

    action(*arguments)

    assert custom_edit.read_text(encoding="utf-8") == "/* GUI edit */\n"
    assert (
        workspace / "gpgpu_platform/hw/gpgpu_platform.xsa"
    ).read_text(encoding="utf-8") == "new source\n"


def test_project_rejects_structural_config_that_disagrees_with_default(tmp_path: Path) -> None:
    config = make_repo(tmp_path)
    config.cpu = "different_cpu"
    project_task = tasks_by_name(config)["vitis:project"]
    action, arguments = project_task["actions"][0]

    with pytest.raises(ValueError, match="does not match hardware.vitis configuration"):
        action(*arguments)

    workspace = tmp_path / "build/software/vitis"
    assert not (workspace / "gpgpu_platform").exists()
    assert not (workspace / "gpgpu_host").exists()


def test_project_materialization_rejects_unsafe_zip_member(tmp_path: Path) -> None:
    make_repo(tmp_path)
    archive = tmp_path / "tools/hardware/vitis/default-project.zip"
    with zipfile.ZipFile(archive, "w") as project:
        project.writestr("../escape.txt", "bad")

    with pytest.raises(ValueError, match="Unsafe path"):
        vitis.materialize_default_project(
            archive,
            tmp_path / "build/software/vitis",
            tmp_path,
            tmp_path / "build/hardware/platform/gpgpu_platform.xsa",
            "gpgpu_platform",
            "gpgpu_host",
            "ps7_cortexa9_0",
            "standalone_ps7_cortexa9_0",
            "standalone",
            "empty_application",
            (),
        )
    assert not (tmp_path / "escape.txt").exists()


def test_project_materialization_is_atomic_on_invalid_component(tmp_path: Path) -> None:
    make_repo(tmp_path)
    archive = tmp_path / "tools/hardware/vitis/default-project.zip"
    with zipfile.ZipFile(archive, "w") as project:
        project.writestr(
            "gpgpu_platform/vitis-comp.json",
            json.dumps({"name": "gpgpu_platform", "configuration": {}}),
        )
        project.writestr("gpgpu_host/vitis-comp.json", "not-json")

    workspace = tmp_path / "build/software/vitis"
    with pytest.raises(ValueError, match="Invalid Vitis component metadata"):
        vitis.materialize_default_project(
            archive,
            workspace,
            tmp_path,
            tmp_path / "build/hardware/platform/gpgpu_platform.xsa",
            "gpgpu_platform",
            "gpgpu_host",
            "ps7_cortexa9_0",
            "standalone_ps7_cortexa9_0",
            "standalone",
            "empty_application",
            (),
        )
    assert not (workspace / "gpgpu_platform").exists()
    assert not (workspace / "gpgpu_host").exists()


def test_export_workspace_creates_portable_archive_and_excludes_products(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "build/software/vitis"
    platform = workspace / "gpgpu_platform"
    host = workspace / "gpgpu_host"
    (platform / "hw").mkdir(parents=True)
    (host / "src").mkdir(parents=True)
    (host / "build").mkdir(parents=True)
    (platform / "export").mkdir(parents=True)
    (platform / "bsp/libsrc/build_configs/gen_bsp").mkdir(parents=True)
    (platform / "vitis-comp.json").write_text(
        json.dumps(
            {
                "name": "gpgpu_platform",
                "configuration": {
                    "xsa": str(tmp_path / "build/hardware/platform/gpgpu_platform.xsa")
                },
            }
        ),
        encoding="utf-8",
    )
    (host / "vitis-comp.json").write_text(
        json.dumps({"name": "gpgpu_host", "platform": "gpgpu_platform"}),
        encoding="utf-8",
    )
    (host / "src/UserConfig.cmake").write_text(
        f'set(USER_COMPILE_SOURCES "{tmp_path}/software/host/xc7z020/main.c")\n',
        encoding="utf-8",
    )
    (host / "src/app.yaml").write_text(
        "app_src_dir: /opt/Xilinx/2026.1/Vitis/data/embeddedsw/lib/sw_apps/empty_application\n",
        encoding="utf-8",
    )
    (platform / "hw/gpgpu_platform.xsa").write_bytes(b"xsa")
    (host / "build/gpgpu_host.elf").write_bytes(b"elf")
    (platform / "export/generated.bit").write_bytes(b"bit")
    (platform / "bsp/libsrc/build_configs/gen_bsp/build.ninja").write_text(
        f"source = {tmp_path}/private.c\n", encoding="utf-8"
    )

    archive = tmp_path / "tools/hardware/vitis/default-project.zip"
    vitis.export_workspace(
        workspace,
        archive,
        tmp_path,
        "gpgpu_platform",
        "gpgpu_host",
    )

    with zipfile.ZipFile(archive) as exported:
        names = set(exported.namelist())
        assert "gpgpu_platform/vitis-comp.json" in names
        assert "gpgpu_host/vitis-comp.json" in names
        assert "gpgpu_host/src/UserConfig.cmake" in names
        assert not any("/build/" in f"/{name}" for name in names)
        assert not any("/build_configs/" in f"/{name}" for name in names)
        assert not any("/export/" in f"/{name}" for name in names)
        all_text = "\n".join(
            exported.read(name).decode("utf-8")
            for name in names
            if name.endswith((".json", ".cmake", ".yaml", ".yml", ".txt", ".tcl"))
        )
    assert str(tmp_path) not in all_text
    assert "${GPGPU_XSA}" in all_text
    assert "${GPGPU_REPO_ROOT}" in all_text
    assert "${XILINX_VITIS}" in all_text
    assert "/opt/Xilinx" not in all_text
    assert (platform / "vitis-comp.json").stat().st_mtime_ns >= archive.stat().st_mtime_ns
    assert (host / "vitis-comp.json").stat().st_mtime_ns >= archive.stat().st_mtime_ns

    os.utime(archive, (1, 1))
    original_bytes = archive.read_bytes()
    vitis.export_workspace(
        workspace,
        archive,
        tmp_path,
        "gpgpu_platform",
        "gpgpu_host",
    )
    assert archive.read_bytes() == original_bytes
    assert archive.stat().st_mtime_ns == 1_000_000_000


def test_export_refuses_workspace_with_missing_components(tmp_path: Path) -> None:
    workspace = tmp_path / "build/software/vitis"
    workspace.mkdir(parents=True)

    with pytest.raises(FileNotFoundError, match="gpgpu_platform"):
        vitis.export_workspace(
            workspace,
            tmp_path / "default-project.zip",
            tmp_path,
            "gpgpu_platform",
            "gpgpu_host",
        )


def test_export_refuses_symbolic_links(tmp_path: Path) -> None:
    workspace = tmp_path / "build/software/vitis"
    for component in ("gpgpu_platform", "gpgpu_host"):
        root = workspace / component
        root.mkdir(parents=True)
        (root / "vitis-comp.json").write_text(
            json.dumps({"name": component, "configuration": {}}),
            encoding="utf-8",
        )
    outside = tmp_path / "outside.txt"
    outside.write_text("private", encoding="utf-8")
    (workspace / "gpgpu_host/linked.txt").symlink_to(outside)

    with pytest.raises(ValueError, match="symbolic link"):
        vitis.export_workspace(
            workspace,
            tmp_path / "default-project.zip",
            tmp_path,
            "gpgpu_platform",
            "gpgpu_host",
        )


def test_committed_default_project_is_portable_and_matches_default_config() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    archive = repo_root / "tools/hardware/vitis/default-project.zip"

    with zipfile.ZipFile(archive) as project:
        names = set(project.namelist())
        assert "gpgpu_platform/vitis-comp.json" in names
        assert "gpgpu_host/vitis-comp.json" in names
        assert not any("/build/" in f"/{name}" for name in names)
        assert not any("/build_configs/" in f"/{name}" for name in names)
        assert not any("/export/" in f"/{name}" for name in names)

        platform = json.loads(project.read("gpgpu_platform/vitis-comp.json"))
        host = json.loads(project.read("gpgpu_host/vitis-comp.json"))
        user_config = project.read("gpgpu_host/src/UserConfig.cmake").decode()
        app_yaml = project.read("gpgpu_host/src/app.yaml").decode()
        assert platform["name"] == "gpgpu_platform"
        assert platform["configuration"]["xsa"] == "${GPGPU_XSA}"
        assert host["name"] == "gpgpu_host"
        assert host["domain"] == "standalone_ps7_cortexa9_0"
        assert user_config.count("${GPGPU_REPO_ROOT}/software/host/xc7z020/") == 2
        assert "${XILINX_VITIS}/data/embeddedsw" in app_yaml

        for name in names:
            assert "tsiantosd" not in name.lower(), name
            assert ".xil" not in name.lower(), name
            raw = project.read(name)
            lowered = raw.lower()
            assert b"/home/" not in lowered, name
            assert b"/workspace/" not in lowered, name
            assert b"/opt/xilinx" not in lowered, name
            assert b"tsiantosd" not in lowered, name
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                continue
            assert "/home/" not in text, name
            assert "/workspace/" not in text, name
            assert "tsiantosd" not in text.lower(), name


def test_fake_vitis_launcher_builds_platform_before_host(tmp_path: Path) -> None:
    config = make_repo(tmp_path)
    fake = tmp_path / "fake-vitis"
    fake.write_text(
        "#!/usr/bin/env python3\n"
        "from pathlib import Path\n"
        "import sys\n"
        "workspace = Path(sys.argv[sys.argv.index('--workspace') + 1])\n"
        "component = sys.argv[sys.argv.index('--component') + 1]\n"
        "with (workspace / 'fake-build-order.log').open('a') as log:\n"
        "    log.write(component + '\\n')\n"
        "if component == 'gpgpu_platform':\n"
        "    out = workspace / component / 'export/gpgpu_platform/hw/sdt'\n"
        "    out.mkdir(parents=True, exist_ok=True)\n"
        "    (out.parent / 'gpgpu_platform.xsa').write_bytes(b'xsa')\n"
        "    (out / 'ps7_init.tcl').write_text('# init\\n')\n"
        "    (workspace / component / 'export/gpgpu_platform/gpgpu_platform.xpfm').write_text('xpfm\\n')\n"
        "else:\n"
        "    out = workspace / component / 'build'\n"
        "    out.mkdir(parents=True, exist_ok=True)\n"
        "    (out / 'gpgpu_host.elf').write_bytes(b'elf')\n",
        encoding="utf-8",
    )
    fake.chmod(0o755)
    config.vitis_command = str(fake)
    tasks = tasks_by_name(config)

    for task_name in (
        "vitis:project",
        "vitis:build:platform",
        "vitis:build:host",
    ):
        action, arguments = tasks[task_name]["actions"][0]
        action(*arguments)

    workspace = tmp_path / "build/software/vitis"
    assert (workspace / "gpgpu_platform/export/gpgpu_platform/hw/gpgpu_platform.xsa").is_file()
    assert (workspace / "gpgpu_platform/export/gpgpu_platform/hw/sdt/ps7_init.tcl").is_file()
    assert (workspace / "gpgpu_platform/export/gpgpu_platform/gpgpu_platform.xpfm").is_file()
    assert (workspace / "gpgpu_host/build/gpgpu_host.elf").is_file()
    assert (workspace / "fake-build-order.log").read_text().splitlines() == [
        "gpgpu_platform",
        "gpgpu_host",
    ]
