# Vivado CLI flow

The generated Vivado project is not tied to a checkout path. The CLI resolves
the repository root at runtime, references RTL from `hardware/rtl/`, and uses
`hardware/constraints/zedboard.xdc` from the same checkout.

## Prerequisite

Vivado 2026.1 must be available as `vivado`, or configured locally without
changing the shared profile:

```yaml
# config/local.yaml
tools:
  vivado:
    command: /opt/Xilinx/Vivado/2026.1/bin/vivado
```

`config/local.yaml` is ignored by Git.

## Stages

Each command depends on the stage above it, so invoking a later stage runs any
missing or out-of-date prerequisites automatically:

```text
vivado:extract-block-design (when an existing project/BD is present)
  └─ vivado:project
       └─ vivado:block-design
            └─ vivado:synthesis
                 └─ vivado:implementation
                      └─ vivado:bitstream
                           └─ vivado:xsa
```

`architecture.num_cores` is the shared core-count setting. The RTL test flow
passes it to both testbench top-level parameters and expected-memory generation;
software-program builds receive it as the `GPGPU_NUM_CORES` C preprocessor
macro; and the Vivado block-design stage applies it to `GPGPU.SP_PER_SM` before
generating the HDL wrapper. Changing it invalidates the relevant task commands
and causes the software, RTL simulator, and Vivado synthesis artifacts to be
rebuilt.

Run one stage with:

```bash
./gpgpu run vivado:project
./gpgpu run vivado:block-design
./gpgpu run vivado:synthesis
./gpgpu run vivado:implementation
./gpgpu run vivado:bitstream
./gpgpu run vivado:xsa
```

`vivado:xsa` exports a fixed hardware platform with the bitstream included,
matching **File → Export → Export Hardware → Include bitstream** from the GUI.
It does not generate a separate configuration-memory binary and does not run
Vitis.

The aggregate command runs the complete chain through both output artifacts:

```bash
./gpgpu run vivado:all
```

## Synchronizing GUI block-design changes

After opening `build/hardware/vivado/GPU/GPU.xpr` in Vivado, editing
`gpgpu_block_design`, and saving the block design, close the GUI project before
running `vivado:all`.

At the start of the dependency chain, `vivado:extract-block-design` behaves as
follows:

- if no generated project exists (for example, after a fresh clone), it keeps
  and uses the committed `tools/hardware/vivado/gpgpu_block_design.tcl`;
- if the project and `gpgpu_block_design.bd` exist, it runs `write_bd_tcl`,
  normalizes the export, and atomically refreshes the committed Tcl only when
  its content changed;
- if the project contains a differently named `.bd`, it stops before project
  recreation so an existing design cannot be deleted accidentally.

The extraction task can also be invoked directly:

```bash
./gpgpu run vivado:extract-block-design
```

The strict/manual equivalent remains available:

```bash
./gpgpu run vivado:export-block-design
```

Unlike the conditional extraction stage, the manual command reports an error
if the configured project or block design does not exist. Both commands check
for machine-specific absolute paths and compare normalized content rather than
timestamps. `architecture.num_cores` remains config-owned and is normalized to
`$::NUM_CORES` instead of being captured as a machine/project-specific value.

If the committed Tcl differs from the block design, the command prints a
warning and updates it atomically. If there is no difference, it reports that
the Tcl is up to date. The comparison is content-based rather than timestamp-
based.

The task exports the project managed by this CLI. It does not guess or discover
unrelated Vivado projects elsewhere on the machine. To import the current
legacy `/workspace/GPU/GPU.xpr` project once, override only the configured
Vivado project parent:

```bash
./gpgpu --set paths.build.hardware.vivado=/workspace \
  run vivado:export-block-design
```

The project name remains the configured `GPU`, so the resolved project is
`/workspace/GPU/GPU.xpr`. Normal operation should use the generated project
under `build/`.

Generated project state is written to `build/hardware/vivado/GPU/`. The final
outputs are:

```text
build/hardware/bitstream/gpgpu_block_design_wrapper.bit
build/hardware/platform/gpgpu_platform.xsa
```

Use `hardware.vivado.jobs` in a profile/local override, or a one-off CLI
override, to control Vivado parallelism:

```bash
./gpgpu --set hardware.vivado.jobs=8 run vivado:bitstream
```

All project, block-design, run, and output-product files under `build/` are
generated and may be deleted and recreated from the committed Tcl, RTL, and
XDC sources.