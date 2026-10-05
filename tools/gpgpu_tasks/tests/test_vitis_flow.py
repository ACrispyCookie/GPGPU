"""Exercise the real Vitis entry point without requiring the vendor SDK."""

from pathlib import Path
import runpy
import subprocess
import sys
from types import ModuleType

import pytest


FLOW_SCRIPT = Path(__file__).resolve().parents[3] / "tools/hardware/vitis/vitis_flow.py"


@pytest.mark.parametrize("separator", [True, False])
@pytest.mark.parametrize("component_name", ["gpgpu_platform", "gpgpu_host"])
def test_build_arguments_reach_sdk_with_or_without_launcher_separator(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    separator: bool, component_name: str,
) -> None:
    component_root = tmp_path / component_name
    component_root.mkdir()
    (component_root / "vitis-comp.json").write_text("{}", encoding="utf-8")
    calls = []

    class Component:
        def build(self):
            calls.append(("build", component_name))
            return True

    class Client:
        def set_workspace(self, workspace):
            calls.append(("workspace", workspace))

        def get_component(self, *, name):
            calls.append(("component", name))
            return Component()

    sdk = ModuleType("vitis")
    setattr(sdk, "create_client", Client)
    monkeypatch.setitem(sys.modules, "vitis", sdk)
    arguments = [str(FLOW_SCRIPT)]
    if separator:
        arguments.append("--")
    arguments.extend([
        "build", "--workspace", str(tmp_path), "--component", component_name,
    ])
    monkeypatch.setattr(sys, "argv", arguments)

    runpy.run_path(str(FLOW_SCRIPT), run_name="__main__")

    assert calls == [
        ("workspace", str(tmp_path.resolve())),
        ("component", component_name),
        ("build", component_name),
    ]


@pytest.mark.parametrize("needs_update", [True, False])
def test_workspace_version_error_is_updated_but_other_errors_propagate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, needs_update: bool,
) -> None:
    root = tmp_path / "gpgpu_platform"
    root.mkdir()
    metadata = root / "vitis-comp.json"
    metadata.write_text("{}", encoding="utf-8")
    calls = []
    message = (
        "Cannot set workspace, status = StatusCode.INVALID_ARGUMENT, "
        "Vitis IDE cannot recognize the workspace version. "
        "Click 'Update' to initialize the workspace metadata."
        if needs_update else "Cannot set workspace: permission denied"
    )

    class Client:
        def set_workspace(self, workspace):
            calls.append("set")
            if calls.count("set") == 1:
                raise Exception(message)

        def update_workspace(self, *, path):
            assert path == str(tmp_path.resolve())
            calls.append("update")

        def get_component(self, *, name):
            assert name == "gpgpu_platform"
            return self

        def build(self):
            calls.append("build")
            return True

    sdk = ModuleType("vitis")
    setattr(sdk, "create_client", Client)
    monkeypatch.setitem(sys.modules, "vitis", sdk)
    module = runpy.run_path(str(FLOW_SCRIPT))
    if needs_update:
        module["build_component"](tmp_path, "gpgpu_platform")
        assert calls == ["set", "update", "set", "build"]
    else:
        with pytest.raises(Exception, match="permission denied"):
            module["build_component"](tmp_path, "gpgpu_platform")
        assert calls == ["set"]
    assert metadata.read_text(encoding="utf-8") == "{}"



@pytest.mark.parametrize("bsp_relative", [
    "zynq_fsbl/zynq_fsbl_bsp",
    "ps7_cortexa9_0/standalone_ps7_cortexa9_0/bsp",
])
def test_build_recovers_missing_bsp_lib_directory_and_stale_cmake_configuration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, bsp_relative: str,
) -> None:
    workspace = tmp_path / "relocated checkout with spaces" / "workspace"
    root = workspace / "custom_platform"
    root.mkdir(parents=True)
    (root / "vitis-comp.json").write_text("{}", encoding="utf-8")
    bsp = root / bsp_relative
    sources = bsp / "libsrc" / "xiltimer" / "src"
    sources.mkdir(parents=True)
    marker = bsp / "timer-subdirectory-built.txt"
    (sources / "CMakeLists.txt").write_text(
        'add_custom_target(timer ALL COMMAND ${CMAKE_COMMAND} -E touch "'
        + marker.as_posix() + '\")\n', encoding="utf-8",
    )
    cmake_source = bsp / "CMakeLists.txt"
    cmake_source.write_text(
        'cmake_minimum_required(VERSION 3.15)\nproject(bsp NONE)\n'
        'set(BSP_LIBSRC_SUBDIRS xiltimer)\n'
        'foreach(entry ${BSP_LIBSRC_SUBDIRS})\n'
        'set(path "${CMAKE_LIBRARY_PATH}/../libsrc/${entry}/src")\n'
        'if(EXISTS "${path}")\nadd_subdirectory("${path}" timer)\nendif()\n'
        'endforeach()\n', encoding="utf-8",
    )
    build = bsp / "libsrc/build_configs/gen_bsp"
    subprocess.run([
        "cmake", "-G", "Unix Makefiles", "-S", str(bsp), "-B", str(build),
        f"-DCMAKE_LIBRARY_PATH={bsp / 'lib'}",
    ], check=True, capture_output=True, text=True)
    subprocess.run(["cmake", "--build", str(build)], check=True, capture_output=True)
    assert not marker.exists()  # Reproduce the silently skipped library target.
    old_mtime = cmake_source.stat().st_mtime_ns

    class Client:
        def set_workspace(self, path):
            assert path == str(workspace.resolve())

        def get_component(self, *, name):
            assert name == "custom_platform"
            return self

        def build(self):
            assert (bsp / "lib").is_dir()
            subprocess.run(["cmake", "--build", str(build)], check=True,
                           capture_output=True, text=True)
            assert marker.is_file()
            return True

    sdk = ModuleType("vitis")
    setattr(sdk, "create_client", Client)
    monkeypatch.setitem(sys.modules, "vitis", sdk)
    module = runpy.run_path(str(FLOW_SCRIPT))
    module["build_component"](workspace, "custom_platform")
    assert cmake_source.stat().st_mtime_ns > old_mtime
    repaired_mtime = cmake_source.stat().st_mtime_ns
    module["build_component"](workspace, "custom_platform")
    assert cmake_source.stat().st_mtime_ns == repaired_mtime


@pytest.mark.parametrize("service_dir", ["xilrsa", "xilrsa_v1_9"])
def test_missing_rsa_vendor_input_is_restored_from_relocated_sdk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, service_dir: str,
) -> None:
    sdk_root = tmp_path / "relocated SDK with spaces"
    vendor_input = sdk_root / "data/embeddedsw/lib/sw_services" / service_dir / "src/librsa.a"
    vendor_input.parent.mkdir(parents=True)
    vendor_input.write_bytes(b"!<arch>\n")  # Minimal archive for the isolated SDK fixture.
    sdk = ModuleType("vitis")
    sdk.__file__ = str(sdk_root / "cli/vitis/__init__.py")
    monkeypatch.setitem(sys.modules, "vitis", sdk)
    component_root = tmp_path / "arbitrary workspace/custom_platform"
    bsp = component_root / "custom_fsbl/custom_bsp"
    rsa_source = bsp / "libsrc/xilrsa/src"
    rsa_source.mkdir(parents=True)
    (bsp / "lib").mkdir()
    cmake_source = bsp / "CMakeLists.txt"
    cmake_source.write_text(
        'cmake_minimum_required(VERSION 3.15)\nproject(bsp NONE)\n'
        'set(BSP_LIBSRC_SUBDIRS xilrsa)\n'
        'set(path "${CMAKE_LIBRARY_PATH}/../libsrc/xilrsa/src")\n'
        'if(EXISTS "${path}")\nadd_subdirectory("${path}" rsa)\nendif()\n',
        encoding="utf-8",
    )
    (rsa_source / "CMakeLists.txt").write_text(
        'file(COPY "${CMAKE_CURRENT_SOURCE_DIR}/librsa.a" '
        'DESTINATION "${CMAKE_BINARY_DIR}")\n', encoding="utf-8",
    )
    build = bsp / "libsrc/build_configs/gen_bsp"
    command = ["cmake", "-G", "Unix Makefiles", "-S", str(bsp), "-B", str(build),
               f"-DCMAKE_LIBRARY_PATH={bsp / 'lib'}"]
    failed = subprocess.run(command, capture_output=True, text=True)
    assert failed.returncode != 0 and "librsa.a" in failed.stderr
    old_mtime = cmake_source.stat().st_mtime_ns
    module = runpy.run_path(str(FLOW_SCRIPT))
    module["prepare_bsp_output_directories"](component_root)
    restored = rsa_source / "librsa.a"
    assert restored.read_bytes() == vendor_input.read_bytes()
    assert cmake_source.stat().st_mtime_ns > old_mtime
    subprocess.run(command, check=True, capture_output=True, text=True)
    assert (build / "librsa.a").read_bytes() == vendor_input.read_bytes()
    # Existing inputs are preserved, and repeated preparation is a no-op.
    restored.write_bytes(b"existing input")
    repaired_mtime = cmake_source.stat().st_mtime_ns
    module["prepare_bsp_output_directories"](component_root)
    assert restored.read_bytes() == b"existing input"
    assert cmake_source.stat().st_mtime_ns == repaired_mtime


@pytest.mark.parametrize("ambiguous", [False, True])
def test_rsa_sdk_discovery_fails_clearly_without_guessing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ambiguous: bool,
) -> None:
    sdk = ModuleType("vitis")
    sdk.__file__ = str(tmp_path / "sdk/cli/vitis/__init__.py")
    if ambiguous:
        for version in ("xilrsa_v1_8", "xilrsa_v1_9"):
            archive = tmp_path / "sdk/data/embeddedsw/lib/sw_services" / version / "src/librsa.a"
            archive.parent.mkdir(parents=True)
            archive.write_bytes(b"!<arch>\n")
    monkeypatch.setitem(sys.modules, "vitis", sdk)
    module = runpy.run_path(str(FLOW_SCRIPT))
    exception = RuntimeError if ambiguous else FileNotFoundError
    match = "Ambiguous" if ambiguous else "active Vitis SDK"
    with pytest.raises(exception, match=match):
        module["installed_rsa_archive"]()
