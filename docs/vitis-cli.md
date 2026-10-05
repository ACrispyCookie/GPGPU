# Vitis CLI flow

The repository keeps a portable exported Vitis 2026.1 project at:

```text
tools/hardware/vitis/default-project.zip
```

The editable project is generated at:

```text
build/software/vitis/
├── gpgpu_platform/
└── gpgpu_host/
```

Generated workspace files are ignored by Git. The ZIP is the committed default used for a clean checkout.

## Configuration

The default profile contains the reproducible Vitis contract:

```yaml
hardware:
  vitis:
    version: "2026.1"
    platform_name: gpgpu_platform
    host_name: gpgpu_host
    cpu: ps7_cortexa9_0
    domain: standalone_ps7_cortexa9_0
    os: standalone
    template: empty_application
    default_archive: tools/hardware/vitis/default-project.zip
    host_sources:
      - software/host/xc7z020/gpgpu_host.c
      - software/host/xc7z020/main.c
```

During `vitis:project`, the CPU/domain/OS/template settings are validated against
the committed export, while `host_sources` regenerates the workspace's
`USER_COMPILE_SOURCES` block. This prevents the YAML contract and the exported
project from silently drifting apart. Structural changes should be exported from
Vitis together with the matching YAML update.

If both workspace components already exist, `vitis:project` refreshes only the
configured XSA, platform metadata, and host source list. Other editable Vitis
files are preserved. A partially present workspace is rejected rather than
overwritten.

Set a machine-specific launcher in `config/local.yaml` when `vitis` is not on `PATH`:

```yaml
tools:
  vitis:
    command: /opt/Xilinx/2026.1/Vitis/bin/vitis
```

## Dependency graph

```text
vivado:xsa
  └─ vitis:project
       └─ vitis:build:platform
            └─ vitis:build:host
                 └─ vitis:build:all
```

The `vivado:xsa` dependency is added only when the configured XSA does not
already exist. Normal Vitis workspace creation therefore reuses the existing XSA
instead of needlessly rebuilding the Vivado project.

`vitis:export` is intentionally outside the build graph. A normal build never modifies tracked project defaults.

## Create and edit the project

```bash
./gpgpu run vitis:project
```

On a clean workspace, this extracts the committed project, replaces portable
path markers with paths for the current checkout, and copies the current
`build/hardware/platform/gpgpu_platform.xsa` into the generated platform
component. On an existing complete workspace, it performs the non-destructive
refresh described above.

Open `build/software/vitis` as the Vitis workspace. Changes made there remain available between CLI invocations because the project task is target-based. Do not delete the workspace before exporting changes that should become the new repository default.

## Build

```bash
./gpgpu run vitis:build:platform
./gpgpu run vitis:build:host
./gpgpu run vitis:build:all
```

Expected outputs are:

```text
build/software/vitis/gpgpu_platform/export/gpgpu_platform/hw/gpgpu_platform.xsa
build/software/vitis/gpgpu_platform/export/gpgpu_platform/hw/sdt/ps7_init.tcl
build/software/vitis/gpgpu_platform/export/gpgpu_platform/gpgpu_platform.xpfm
build/software/vitis/gpgpu_host/build/gpgpu_host.elf
```

The platform build always precedes the host build because the application consumes the exported standalone platform domain and BSP.

The programming bitstream is published separately by Vivado at
`build/hardware/bitstream/gpgpu_block_design_wrapper.bit`. The Vitis platform
export does not provide a standalone `hw/sdt/gpgpu_platform.bit` in this flow;
its XSA includes the bitstream. Use the Vivado-published `.bit`, the exported
`ps7_init.tcl`, and the host ELF for board programming. See
[FPGA upload](fpga-cli.md) for transferring these three files to the
board-connected machine without rebuilding or programming the board.

### Portable BSP directory initialization and recovery

Before calling the Vitis component build API, the CLI discovers BSP roots from
their `CMakeLists.txt` and `libsrc/` source tree inside the selected component.
It recreates a missing `lib/` output directory for each matching BSP, including
both the FSBL BSP and the application-domain BSP. This is necessary because the
vendor CMake scripts check source paths via `lib/../libsrc/`; without `lib/`, those
checks can silently skip all library targets and later produce linker errors
such as `cannot find -lxil`.

The paths are derived from the configured workspace and component, not a user's
home directory, a fixed checkout location, or a fixed Xilinx installation path.
Generated library binaries remain excluded from the portable archive. When a
missing directory is repaired, the CLI updates only the generated BSP
`CMakeLists.txt` timestamp to trigger CMake regeneration of an existing build
graph; file contents, cached toolchain settings, and editable sources are
preserved. Subsequent builds do not repeat that timestamp update.

The FSBL RSA service also requires `libsrc/xilrsa/src/librsa.a`. Unlike the
BSP's generated `libxilrsa.a`, this is a prebuilt vendor **input** consumed by
CMake at configuration time. When missing, the CLI restores it from the
`data/embeddedsw/lib/sw_services/xilrsa*/src/` tree of the active Vitis SDK.
The SDK root is discovered from the loaded `vitis` Python module, not a
hardcoded `/opt/Xilinx` path or an unrelated system installation. Both
unversioned `xilrsa` and a single versioned `xilrsa_v*` service directory are
supported; missing or ambiguous inputs fail with an explicit diagnostic.
Existing workspace RSA inputs are left unchanged. This restoration also
triggers CMake regeneration and needs no network downloads or archive changes.

To retry an affected workspace, run `./gpgpu run vitis:build:all` normally; there
is no need to delete the workspace, copy libraries from another machine, or edit
`ps7_init.c`. Vivado and Vitis matching the configured flow version must still be
installed and their launchers available through `PATH` or local configuration.

## Export GUI changes back to the repository

Save and close the Vitis workspace, then run:

```bash
./gpgpu run vitis:export
```

The command atomically replaces `tools/hardware/vitis/default-project.zip`. It:

- includes the `gpgpu_platform` and `gpgpu_host` component source state;
- converts checkout, workspace, XSA, and Xilinx installation paths into portable markers;
- excludes component `build/`, `export/`, `logs/`, `.Xil/`, generated library/object/dependency files, and the embedded XSA;
- rejects symbolic links and machine-specific paths in text or binary payloads;
- verifies that both component metadata files are present before replacement.

Review the resulting ZIP change before committing it. Running `vitis:project` in a clean build tree will recreate an editable project from this new default.
