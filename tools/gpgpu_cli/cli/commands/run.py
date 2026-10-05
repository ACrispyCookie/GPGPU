"""Execute one pydoit task from the resolved project graph."""

from __future__ import annotations

import re

import typer
from rich.markup import escape
from src import run_logged_task

from config import ConfigError, ResolvedConfig

_TASK_HELP = """A colon-separated task name from the GPGPU build graph.

Possible values:

[bold cyan]Programs[/bold cyan] (`<program>` is a directory under `software/programs`)

• `software:programs:<program>:x86` — Build and run the native x86 executable.

• `software:programs:<program>:x86:build` — Build the native x86 executable without running it.

• `software:programs:<program>:elf` — Compile and link the RISC-V ELF executable.

• `software:programs:<program>:dump` — Generate the complete RISC-V disassembly.

• `software:programs:<program>:assembly` — Generate the cleaned RISC-V assembly listing.

• `software:programs:<program>:mem` — Generate the instruction-memory image.

• `software:programs:<program>:riscv:build` — Build the RISC-V program assembly and its dependencies.

• `software:programs:<program>:all` — Build both the native x86 executable and RISC-V assembly.

Example: `software:programs:simple:x86`

[bold cyan]Tests[/bold cyan]

• `tests:rtl:generate` — Generate shared test programs and expected-memory files.

• `tests:rtl:e2e:build` — Build the end-to-end `tb_GPGPU_e2e.v` suite.

• `tests:rtl:e2e:run` — Run the end-to-end suite through the host command interface.

• `tests:rtl:e2e:all` — Generate, build, and run the end-to-end suite.

• `tests:rtl:smx:build` — Build the SMX-only `tb_GPGPU.v` suite.

• `tests:rtl:smx:run` — Run the SMX-only suite with direct memory access.

• `tests:rtl:smx:all` — Generate, build, and run the SMX-only suite.

• `tests:rtl:random` — Generate and run reproducible random programs on the SMX testbench. Configure the run with `tests.rtl.random.iterations` and `tests.rtl.random.seed`.

• `tests:rtl:build` — Build both the end-to-end and SMX-only suites.

• `tests:rtl:run` — Run both RTL suites.

• `tests:rtl:all` — Generate, build, and run both RTL suites.

[bold cyan]Vivado[/bold cyan]

The dependency chain is: conditional block-design extraction → project → block design/wrapper → synthesis → implementation → bitstream → XSA hardware platform.

• `vivado:extract-block-design` — If the configured project and block design exist, refresh the committed portable Tcl before any potentially destructive project recreation; otherwise use the committed Tcl as the first-clone bootstrap.

• `vivado:project` — Recreate the generated Vivado project from repository RTL and XDC sources.

• `vivado:block-design` — Recreate `gpgpu_block_design` and generate `gpgpu_block_design_wrapper`.
  The configured `hardware.vivado.host_interface.*` addresses are applied to the five AXI GPIO segments before validation and wrapper generation.

• `vivado:synthesis` — Run synthesis after creating the project and block design.

• `vivado:implementation` — Run implementation through routing after synthesis.

• `vivado:bitstream` — Generate and copy the bitstream after implementation.

• `vivado:xsa` — Export `gpgpu_platform.xsa` with the generated bitstream included, ready for a later Vitis platform flow.

• `vivado:export-block-design` — Strictly export the current generated-project block design on explicit request. Unlike the conditional extraction task, this fails when the project/design is absent.

• `vivado:all` — Conditionally extract an existing block design, then run the complete dependency chain through `.bit` and `.xsa` generation.

[bold cyan]Vitis[/bold cyan]

The dependency chain is: Vivado XSA → editable Vitis project → platform build → host build.

• `vitis:project` — Materialize the committed portable default project under `build/software/vitis/` and bind it to the current checkout's XSA and host sources. The generated project can be opened and edited in Vitis.

• `vitis:build:platform` — Build `gpgpu_platform` and verify its `.xsa`, `.xpfm`, and `ps7_init.tcl` outputs.

• `vitis:build:host` — Build `gpgpu_host` after the platform and verify `gpgpu_host.elf`.

• `vitis:build:all` — Run the complete Vitis dependency chain through the host ELF.

• `vitis:export` — Explicitly replace the committed default-project archive with a normalized snapshot of the editable generated project. Build products and machine-specific checkout paths are excluded.

[bold cyan]FPGA[/bold cyan]

• `fpga:upload` — SCP the existing Vivado bitstream, Vitis `ps7_init.tcl`, and host ELF to the board-connected VM without building. Configure `hardware.fpga.upload.destination` and `hardware.fpga.upload.directory` (defaults: `njason@192.168.1.13`, `/home/njason/upload`).
"""


def _format_task_help(text: str) -> str:
    """Render task identifiers and inline references using terminal styles."""
    def highlight(match: re.Match[str]) -> str:
        value = match[1]
        style = (
            "bold bright_green"
            if value.startswith(("software:programs:", "tests:rtl:", "vivado:", "vitis:", "fpga:"))
            else "yellow"
        )
        return f"[{style}]{escape(value)}[/{style}]"

    return re.sub(r"`([^`]+)`", highlight, text)


def run(
    ctx: typer.Context,
    task: str = typer.Argument(..., metavar="TASK", help=_format_task_help(_TASK_HELP)),
    plain: bool = typer.Option(
        False, "--plain", help="Stream plain logs instead of the interactive build monitor."
    ),
) -> None:
    """Run one task and all of its dependencies from the GPGPU build graph."""

    config: ResolvedConfig = ctx.obj
    try:
        _ = config.build_root
    except ConfigError as exc:
        raise typer.BadParameter(str(exc)) from exc
    status = run_logged_task(config, task, monitor=False) if plain else run_logged_task(config, task)
    if status:
        raise typer.Exit(status)
